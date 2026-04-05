from collections import Counter
from typing import Any
import re

from ..core.config import settings
from ..models.schemas import GraphChangeSummary, GraphCompareSummary, GraphContext, GraphStatus, PolicyRecord

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover
    GraphDatabase = None


class GraphService:
    def __init__(self) -> None:
        self._driver = None
        self._configured = settings.neo4j_enabled and GraphDatabase is not None
        self._detail = "Neo4j not configured."
        if self._configured:
            try:
                self._driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_username, settings.neo4j_password),
                )
                self._driver.verify_connectivity()
                self._detail = "Neo4j connected."
            except Exception as exc:
                self._driver = None
                self._detail = f"Neo4j unavailable: {exc}"

    def get_status(self) -> GraphStatus:
        return GraphStatus(configured=self._configured, connected=self._driver is not None, detail=self._detail)

    def initialize_schema(self) -> None:
        if not self._driver:
            return
        statements = [
            "CREATE CONSTRAINT payer_name_unique IF NOT EXISTS FOR (p:Payer) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT policy_key_unique IF NOT EXISTS FOR (p:Policy) REQUIRE p.policy_key IS UNIQUE",
            "CREATE CONSTRAINT policy_version_doc_id_unique IF NOT EXISTS FOR (v:PolicyVersion) REQUIRE v.doc_id IS UNIQUE",
            "CREATE CONSTRAINT drug_brand_unique IF NOT EXISTS FOR (d:Drug) REQUIRE d.brand_name IS UNIQUE",
            "CREATE CONSTRAINT requirement_key_unique IF NOT EXISTS FOR (r:Requirement) REQUIRE r.requirement_key IS UNIQUE",
            "CREATE CONSTRAINT indication_snapshot_key_unique IF NOT EXISTS FOR (i:IndicationSnapshot) REQUIRE i.snapshot_key IS UNIQUE",
            "CREATE CONSTRAINT evidence_key_unique IF NOT EXISTS FOR (e:EvidenceSnippetNode) REQUIRE e.evidence_key IS UNIQUE",
            "CREATE CONSTRAINT hcpcs_code_unique IF NOT EXISTS FOR (c:HCPCSCode) REQUIRE c.code IS UNIQUE",
        ]
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                for statement in statements:
                    session.run(statement).consume()
        except Exception as exc:
            self._detail = f"Neo4j schema initialization failed: {exc}"

    def clear_graph(self) -> None:
        if not self._driver:
            return
        with self._driver.session(database=settings.neo4j_database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

    def persist_policy_record(self, record: PolicyRecord) -> GraphContext:
        if not self._driver:
            return GraphContext(enabled=self._configured, persisted=False, status_message=self._detail)
        payload = self._record_payload(record)
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                session.execute_write(self._upsert_policy_graph, payload)
            context = self.get_policy_context(record.doc_id, record.drug_name_brand)
            return context or GraphContext(enabled=True, persisted=True, status_message="Persisted to Neo4j.")
        except Exception as exc:
            self._detail = f"Neo4j write failed: {exc}"
            return GraphContext(enabled=True, persisted=False, status_message=self._detail)

    def get_policy_context(self, doc_id: str, drug_name: str) -> GraphContext | None:
        if not self._driver:
            return GraphContext(enabled=self._configured, persisted=False, status_message=self._detail)
        query = """
        MATCH (version:PolicyVersion {doc_id: $doc_id})
        OPTIONAL MATCH (version)-[:COVERS]->(drug:Drug)
        OPTIONAL MATCH (version)-[:HAS_REQUIREMENT]->(req:Requirement)
        OPTIONAL MATCH (version)-[:HAS_INDICATION]->(ind:IndicationSnapshot)
        OPTIONAL MATCH (version)-[:HAS_EVIDENCE]->(ev:EvidenceSnippetNode)
        OPTIONAL MATCH (policy:Policy)-[:HAS_VERSION]->(version)
        OPTIONAL MATCH (policy)-[:HAS_VERSION]->(related_version:PolicyVersion)
        WITH version, drug,
             collect(DISTINCT req.requirement_type) AS requirement_types,
             collect(DISTINCT ind.value) AS indications,
             count(DISTINCT ev) AS evidence_count,
             collect(DISTINCT related_version.doc_id) AS known_versions
        OPTIONAL MATCH (other_payer:Payer)-[:PUBLISHES]->(:Policy)-[:HAS_VERSION]->(:PolicyVersion)-[:COVERS]->(drug)
        WITH version, drug, requirement_types, indications, evidence_count, known_versions, collect(DISTINCT other_payer.name) AS known_payers
        OPTIONAL MATCH (version)-[:MENTIONS_BIOSIMILAR]->(biosimilar:Drug)
        RETURN requirement_types, indications, evidence_count, known_versions, known_payers, collect(DISTINCT biosimilar.brand_name) AS biosimilars
        """
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                rows = session.run(query, doc_id=doc_id, drug_name=drug_name).data()
            if not rows:
                return GraphContext(enabled=True, persisted=False, status_message="No graph node found for this document.")
            result = rows[0]
            return GraphContext(
                enabled=True,
                persisted=True,
                status_message="Loaded from Neo4j.",
                known_payers_for_drug=self._clean_list(result.get("known_payers")),
                known_versions_for_policy=self._clean_list(result.get("known_versions")),
                indications_in_graph=self._clean_list(result.get("indications")),
                requirement_types=self._clean_list(result.get("requirement_types")),
                related_biosimilars=self._clean_list(result.get("biosimilars")),
                evidence_count=int(result.get("evidence_count") or 0),
            )
        except Exception as exc:
            self._detail = f"Neo4j read failed: {exc}"
            return GraphContext(enabled=True, persisted=False, status_message=self._detail)

    def summarize_compare(self, drug_name: str, payer_filters: list[str]) -> GraphCompareSummary:
        if not self._driver:
            return GraphCompareSummary(enabled=self._configured, status_message=self._detail)
        query = """
        MATCH (payer:Payer)-[:PUBLISHES]->(:Policy)-[:HAS_VERSION]->(version:PolicyVersion)-[:COVERS]->(drug:Drug)
        WHERE toLower(drug.brand_name) = toLower($drug_name)
          AND (size($payer_filters) = 0 OR payer.name IN $payer_filters)
        RETURN collect(DISTINCT payer.name) AS payer_names,
               collect(version.coverage_status) AS coverage_statuses,
               collect(version.prior_auth_required) AS prior_auths,
               collect(version.step_therapy) AS step_therapies,
               sum(CASE WHEN version.site_of_care IS NOT NULL AND version.site_of_care <> 'unknown' THEN 1 ELSE 0 END) AS site_of_care_restriction_count
        """
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                rows = session.run(query, drug_name=drug_name, payer_filters=payer_filters).data()
            if not rows:
                return GraphCompareSummary(enabled=True, status_message="No graph data found for this drug.")
            result = rows[0]
            payer_names = self._clean_list(result.get("payer_names"))
            return GraphCompareSummary(
                enabled=True,
                status_message="Loaded from Neo4j.",
                payer_count=len(payer_names),
                payer_names=payer_names,
                coverage_status_counts=dict(Counter(self._clean_list(result.get("coverage_statuses")))),
                prior_auth_counts=dict(Counter(self._clean_list(result.get("prior_auths")))),
                step_therapy_counts=dict(Counter(self._clean_list(result.get("step_therapies")))),
                site_of_care_restriction_count=int(result.get("site_of_care_restriction_count") or 0),
            )
        except Exception as exc:
            self._detail = f"Neo4j compare summary failed: {exc}"
            return GraphCompareSummary(enabled=True, status_message=self._detail)

    def summarize_records(self, records: list[PolicyRecord]) -> GraphCompareSummary:
        status = self.get_status()
        return GraphCompareSummary(
            enabled=status.connected,
            status_message="Loaded from Neo4j." if status.connected else status.detail,
            payer_count=len({record.payer for record in records}),
            payer_names=sorted({record.payer for record in records}),
            coverage_status_counts=dict(Counter(record.coverage_status for record in records if record.coverage_status != "unknown")),
            prior_auth_counts=dict(Counter(record.prior_auth_required for record in records if record.prior_auth_required != "unknown")),
            step_therapy_counts=dict(Counter(record.step_therapy for record in records if record.step_therapy != "unknown")),
            site_of_care_restriction_count=sum(1 for record in records if record.site_of_care != "unknown"),
        )

    def summarize_changes(self, old_doc_id: str, new_doc_id: str) -> GraphChangeSummary:
        if not self._driver:
            return GraphChangeSummary(enabled=self._configured, status_message=self._detail)
        query = """
        MATCH (old_version:PolicyVersion {doc_id: $old_doc_id})
        OPTIONAL MATCH (old_version)-[:HAS_INDICATION]->(old_indication:IndicationSnapshot)
        OPTIONAL MATCH (old_version)-[:HAS_REQUIREMENT]->(old_requirement:Requirement)
        WITH collect(DISTINCT old_indication.value) AS old_indications,
             collect(DISTINCT old_requirement.requirement_type) AS old_requirement_types
        MATCH (new_version:PolicyVersion {doc_id: $new_doc_id})
        OPTIONAL MATCH (new_version)-[:HAS_INDICATION]->(new_indication:IndicationSnapshot)
        OPTIONAL MATCH (new_version)-[:HAS_REQUIREMENT]->(new_requirement:Requirement)
        RETURN old_indications,
               old_requirement_types,
               collect(DISTINCT new_indication.value) AS new_indications,
               collect(DISTINCT new_requirement.requirement_type) AS new_requirement_types
        """
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                rows = session.run(query, old_doc_id=old_doc_id, new_doc_id=new_doc_id).data()
            if not rows:
                return GraphChangeSummary(enabled=True, status_message="No graph version data found for this comparison.")
            result = rows[0]
            old_indications = set(self._clean_list(result.get("old_indications")))
            new_indications = set(self._clean_list(result.get("new_indications")))
            old_requirement_types = set(self._clean_list(result.get("old_requirement_types")))
            new_requirement_types = set(self._clean_list(result.get("new_requirement_types")))
            added_indications = sorted(new_indications - old_indications)
            removed_indications = sorted(old_indications - new_indications)
            added_requirement_types = sorted(new_requirement_types - old_requirement_types)
            removed_requirement_types = sorted(old_requirement_types - new_requirement_types)
            return GraphChangeSummary(
                enabled=True,
                status_message="Loaded from Neo4j.",
                added_indications=added_indications,
                removed_indications=removed_indications,
                added_requirement_types=added_requirement_types,
                removed_requirement_types=removed_requirement_types,
                summary=(
                    f"Graph delta: +{len(added_indications)} indications, -{len(removed_indications)} indications, "
                    f"+{len(added_requirement_types)} requirement types, -{len(removed_requirement_types)} requirement types."
                ),
            )
        except Exception as exc:
            self._detail = f"Neo4j change summary failed: {exc}"
            return GraphChangeSummary(enabled=True, status_message=self._detail)

    @staticmethod
    def _upsert_policy_graph(tx: Any, payload: dict[str, Any]) -> None:
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})<-[old_rel:HAS_VERSION]-(:Policy)
            DELETE old_rel
            """,
            payload,
        )
        tx.run(
            """
            MERGE (payer:Payer {name: $payer})
            MERGE (policy:Policy {policy_key: $policy_key})
            SET policy.name = $policy_name,
                policy.payer = $payer,
                policy.document_pattern = $document_pattern
            MERGE (payer)-[:PUBLISHES]->(policy)
            MERGE (version:PolicyVersion {doc_id: $doc_id})
            SET version.version_label = $version_label,
                version.effective_date = $effective_date,
                version.document_pattern = $document_pattern,
                version.status = $status,
                version.coverage_status = $coverage_status,
                version.prior_auth_required = $prior_auth_required,
                version.prior_auth_criteria = $prior_auth_criteria,
                version.step_therapy = $step_therapy,
                version.site_of_care = $site_of_care,
                version.access_status = $access_status,
                version.preferred_status_rank = $preferred_status_rank,
                version.confidence = $confidence,
                version.source_method = $source_method
            MERGE (policy)-[:HAS_VERSION]->(version)
            MERGE (drug:Drug {brand_name: $drug_name_brand})
            SET drug.generic_name = $drug_name_generic,
                drug.category = $drug_category
            MERGE (version)-[:COVERS]->(drug)
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            OPTIONAL MATCH (version)-[:HAS_REQUIREMENT]->(old_requirement:Requirement)
            DETACH DELETE old_requirement
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            OPTIONAL MATCH (version)-[:HAS_INDICATION]->(old_indication:IndicationSnapshot)
            DETACH DELETE old_indication
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            OPTIONAL MATCH (version)-[:HAS_EVIDENCE]->(old_evidence:EvidenceSnippetNode)
            DETACH DELETE old_evidence
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})-[old_rel:MENTIONS_BIOSIMILAR]->(:Drug)
            DELETE old_rel
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})-[old_rel:USES_HCPCS]->(:HCPCSCode)
            DELETE old_rel
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            UNWIND $requirements AS requirement
            MERGE (node:Requirement {requirement_key: requirement.requirement_key})
            SET node.version_doc_id = $doc_id,
                node.requirement_type = requirement.requirement_type,
                node.value = requirement.value
            MERGE (version)-[:HAS_REQUIREMENT]->(node)
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            UNWIND $covered_indications AS indication_value
            MERGE (node:IndicationSnapshot {snapshot_key: $doc_id + '::indication::' + indication_value})
            SET node.version_doc_id = $doc_id,
                node.value = indication_value
            MERGE (version)-[:HAS_INDICATION]->(node)
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            UNWIND $evidence AS evidence
            MERGE (node:EvidenceSnippetNode {evidence_key: evidence.evidence_key})
            SET node.version_doc_id = $doc_id,
                node.page = evidence.page,
                node.section = evidence.section,
                node.snippet = evidence.snippet,
                node.retrieval_method = evidence.retrieval_method
            MERGE (version)-[:HAS_EVIDENCE]->(node)
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            UNWIND $hcpcs_codes AS code_value
            MERGE (code:HCPCSCode {code: code_value})
            MERGE (version)-[:USES_HCPCS]->(code)
            """,
            payload,
        )
        tx.run(
            """
            MATCH (version:PolicyVersion {doc_id: $doc_id})
            UNWIND $biosimilar_reference_relationships AS biosimilar_name
            MERGE (biosimilar:Drug {brand_name: biosimilar_name})
            MERGE (version)-[:MENTIONS_BIOSIMILAR]->(biosimilar)
            """,
            payload,
        )

    def _record_payload(self, record: PolicyRecord) -> dict[str, Any]:
        requirements = []
        for requirement_type, value in {
            "coverage_status": record.coverage_status,
            "prior_auth_required": record.prior_auth_required,
            "prior_auth_criteria": record.prior_auth_criteria,
            "step_therapy": record.step_therapy,
            "site_of_care": record.site_of_care,
            "dosing_quantity_limits": record.dosing_quantity_limits,
            "access_status": record.access_status,
        }.items():
            if value and value != "unknown":
                requirements.append(
                    {
                        "requirement_key": f"{record.doc_id}::{requirement_type}",
                        "requirement_type": requirement_type,
                        "value": self._graph_text(value, 1200),
                    }
                )
        evidence = [
            {
                "evidence_key": f"{record.doc_id}::evidence::{index}",
                "page": snippet.page,
                "section": self._graph_text(snippet.section, 160),
                "snippet": self._graph_text(snippet.snippet, 900),
                "retrieval_method": snippet.retrieval_method,
            }
            for index, snippet in enumerate(record.evidence)
        ]
        return {
            "payer": record.payer,
            "policy_key": self._policy_key(record),
            "policy_name": self._graph_text(record.policy_name, 240),
            "doc_id": record.doc_id,
            "version_label": record.effective_date or "current",
            "effective_date": self._graph_text(record.effective_date, 80),
            "document_pattern": record.document_pattern,
            "status": record.status,
            "coverage_status": self._graph_text(record.coverage_status, 160),
            "prior_auth_required": self._graph_text(record.prior_auth_required, 80),
            "prior_auth_criteria": self._graph_text(record.prior_auth_criteria, 1200),
            "step_therapy": self._graph_text(record.step_therapy, 800),
            "site_of_care": self._graph_text(record.site_of_care, 240),
            "access_status": self._graph_text(record.access_status, 320),
            "preferred_status_rank": self._graph_text(record.preferred_status_rank, 320),
            "confidence": record.confidence,
            "source_method": record.source_method,
            "drug_name_brand": self._graph_text(record.drug_name_brand, 240),
            "drug_name_generic": self._graph_text(record.drug_name_generic, 160),
            "drug_category": self._graph_text(record.drug_category, 240),
            "covered_indications": self._clean_list(record.covered_indications),
            "hcpcs_codes": self._clean_list(record.hcpcs_codes),
            "biosimilar_reference_relationships": self._clean_list(record.biosimilar_reference_relationships),
            "requirements": requirements,
            "evidence": evidence,
        }

    @staticmethod
    def _clean_list(values: list[Any] | None) -> list[Any]:
        if not values:
            return []
        cleaned = []
        seen = set()
        for value in values:
            normalized = GraphService._graph_text(value, 240)
            if normalized in ("", "unknown"):
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)
        return sorted(cleaned)

    @staticmethod
    def _policy_key(record: PolicyRecord) -> str:
        normalized = record.policy_name.lower()
        normalized = re.sub(r"\b(20\d{2}|\d{8})\b", "", normalized)
        normalized = re.sub(rf"\b{re.escape(record.payer.lower())}\b", "", normalized)
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return f"{record.payer}::{normalized}"

    @staticmethod
    def _graph_text(value: Any, limit: int) -> str:
        if value in (None, "", "unknown"):
            return "unknown"
        text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "unknown"
        return text[:limit].rstrip()

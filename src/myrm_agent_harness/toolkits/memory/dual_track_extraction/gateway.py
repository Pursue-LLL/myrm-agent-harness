# [POS] src/myrm_agent_harness/toolkits/memory/dual_track_extraction/gateway.py
# [INPUT] hashlib, logging, re, .types, .classifier
# [OUTPUT] DualTrackExtractionGateway

import hashlib
import logging
import re

from .classifier import DualTrackSemanticClassifier
from .types import (
    ExtractedProceduralRule,
    ExtractedUserFact,
    ExtractionDestiny,
    ExtractionDestinyReport,
    ExtractionTrackKind,
)

logger = logging.getLogger(__name__)


class DualTrackExtractionGateway:
    """Adaptive extraction and routing gateway defending against silent drop defects.

    Guarantees that operational procedures (When/If X, Do Y) are dispatched to ProceduralMemory,
    declarative facts are dispatched to SemanticMemory, and ambiguous/no-signal inputs are
    explicitly reported with structured justification rather than silently vanishing.
    """

    def __init__(
        self,
        classifier: DualTrackSemanticClassifier | None = None,
    ) -> None:
        self.classifier: DualTrackSemanticClassifier = classifier or DualTrackSemanticClassifier()

    def process_utterance(
        self,
        text: str,
        domain: str = "general",
    ) -> ExtractionDestinyReport:
        """Analyze, extract, and deterministically route an incoming utterance."""
        clean_text = text.strip()
        track, confidence, reason = self.classifier.classify(clean_text)

        if track == ExtractionTrackKind.NO_SIGNAL:
            logger.info("Utterance classified as NO_SIGNAL. Discard reason: %s", reason)
            return ExtractionDestinyReport(
                destiny=ExtractionDestiny.DISCARDED_NO_SIGNAL,
                track=track,
                extracted_facts=[],
                extracted_rules=[],
                discard_reason=reason,
                raw_input_text=clean_text,
            )

        extracted_rules: list[ExtractedProceduralRule] = []
        extracted_facts: list[ExtractedUserFact] = []

        if track in (ExtractionTrackKind.PROCEDURAL_RULE, ExtractionTrackKind.DUAL_TRACK):
            rule = self._extract_procedural_rule(clean_text, domain, confidence)
            if rule is not None:
                extracted_rules.append(rule)

        if track in (ExtractionTrackKind.FACT_PROFILE, ExtractionTrackKind.DUAL_TRACK):
            fact = self._extract_user_fact(clean_text, confidence)
            if fact is not None:
                extracted_facts.append(fact)

        # Determine final destiny based on extracted units
        if extracted_rules and extracted_facts:
            destiny = ExtractionDestiny.STORED_DUAL
        elif extracted_rules:
            destiny = ExtractionDestiny.STORED_PROCEDURAL
        elif extracted_facts:
            destiny = ExtractionDestiny.STORED_SEMANTIC
        else:
            destiny = ExtractionDestiny.DISCARDED_NO_SIGNAL
            reason = "Classified as candidate signal but failed structural parsing."

        return ExtractionDestinyReport(
            destiny=destiny,
            track=track,
            extracted_facts=extracted_facts,
            extracted_rules=extracted_rules,
            discard_reason="" if destiny != ExtractionDestiny.DISCARDED_NO_SIGNAL else reason,
            raw_input_text=clean_text,
        )

    def _extract_procedural_rule(
        self,
        text: str,
        domain: str,
        confidence: float,
    ) -> ExtractedProceduralRule | None:
        """Derive condition and action guidelines deterministically from text."""
        rule_hash = hashlib.sha256(text.encode()).hexdigest()[:10]
        rule_id = f"proc-rule-{rule_hash}"

        # Heuristic split between condition and action
        split_match = re.search(r"(遇到|如果|当|一旦|若)(.*?)(记得|务必|必须|先查|先检查|要|一律)(.*)", text)
        if split_match:
            condition = f"{split_match.group(1)}{split_match.group(2).strip()}"
            action = f"{split_match.group(3)}{split_match.group(4).strip()}"
        else:
            condition = "Triggered by operational scenario"
            action = text

        name = text[:36] + ("..." if len(text) > 36 else "")

        return ExtractedProceduralRule(
            rule_id=rule_id,
            name=name,
            trigger_condition=condition,
            action_guideline=action,
            domain=domain,
            confidence=round(confidence, 2),
            raw_source=text,
        )

    def _extract_user_fact(
        self,
        text: str,
        confidence: float,
    ) -> ExtractedUserFact | None:
        """Derive entity-attribute-value triple deterministically from text."""
        fact_hash = hashlib.sha256(text.encode()).hexdigest()[:10]
        fact_id = f"fact-{fact_hash}"

        # Determine entity and attribute
        entity = "user"
        attribute = "profile_detail"
        value = text

        if re.search(r"(数据库|持久化|db|database)", text, re.IGNORECASE):
            entity = "architecture"
            attribute = "database_choice"
        elif re.search(r"(技术栈|语言|python|golang|rust)", text, re.IGNORECASE):
            entity = "preference"
            attribute = "technology_stack"
        elif re.search(r"(名字|称呼|name)", text, re.IGNORECASE):
            entity = "user"
            attribute = "name"

        return ExtractedUserFact(
            fact_id=fact_id,
            entity=entity,
            attribute=attribute,
            value=value,
            confidence=round(confidence, 2),
            raw_source=text,
        )

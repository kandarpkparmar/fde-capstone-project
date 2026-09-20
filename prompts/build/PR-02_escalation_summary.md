prompt_id: PR-02
version: 1.0
serves: FR-07
---
DETERMINISTIC TEMPLATE (no model call, so it also works during a provider outage; see src/route.py:build_escalation_packet).

Summary: "<Intent> ticket via <channel>, <urgency> urgency, <tier> customer. Classified with confidence <c>; alternatives: <a1>, <a2>. Escalated because: <reason>. Relevant documentation: <doc ids + titles>. Not confident about: <list>."

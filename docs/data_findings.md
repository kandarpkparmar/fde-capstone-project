# Data findings (computed by `python -m evaluation.discovery_analysis`; raw numbers in data_findings.json)

* 500 development tickets contain only **216 unique texts**: the data is templated, so classification scores are optimistic.
* **71.4%** of tickets are answerable from the 29 articles. **49.1%** of historical escalations (138 of 281) were answerable ones.
* Historical baseline in the data: first-contact resolution **43.8%**, escalation **56.2%**, CSAT **2.97** (not the 3.2 quoted), median resolution 3.6 hours.
* Interview claims settled by data: Marcus's 42%/58% are close to the data (43.8/56.2); Sofia's claim that non-fluent customers have the worst CSAT is **not supported** (3.04 vs 2.95 fluent); Daniel's "about half of escalations were resolvable" is **supported** (49%); Ravi's belief that enterprise gets faster answers is **contradicted**: enterprise has the slowest median resolution (369 min vs 141 business, 266 standard) and lowest FCR (37%).
* Chat has the lowest CSAT (2.72); documentation comments have the lowest FCR (35%) and longest resolution (465 min) and most repeat contacts (33%).
* Label consistency: **41 of 78** groups of identical ticket text carry conflicting `answerable`/`expected_route` labels; in intents that have documentation, 21% of tickets are labelled not answerable. Nothing in the available fields predicts this (checked tier, urgency, channel, fluency, region, time, length). Consequence: route accuracy against labels has a ceiling of roughly 80%, whatever the system does.
* Urgency is only weakly recoverable from text (out-of-fold accuracy about 50%; majority class 45%).

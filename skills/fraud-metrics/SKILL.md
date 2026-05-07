---
name: dpm-fraud-monitoring-metrics
description: Use this skill when the user asks to calculate, explain, validate, interpret, document, or compare DPM fraud-monitoring KPI metrics: effectiveness, FBP, FBP for self-transfers, FP, AR, CSI, save/lost fraud volumes, false positives, or Central Bank metric differences.
---


## Core Metrics

### 1. Effectiveness

**Russian name:** Эффективность  
**Meaning:** доля мошенничества в рублях, выявленного антифродом, относительно общего объема мошенничества.

Use this metric to estimate how much fraud was detected by fraud monitoring compared with all fraud: detected plus missed.

Formula:

```text
effectiveness = save / (save + lost)
```

Where:

- `save` — prevented fraud, True Positive;
- `lost` — missed fraud, False Negative.

Calculation rules:

- calculate for individuals;
- include channels:
  - ДБО;
  - Карты;
  - ВСП;
  - эквайринг;
- exclude credit operations;
- include only missed fraud from category `КПЭ`;
- do not include accepted fraud as `lost`, because there was already a fraud-monitoring alert and the system detected suspicious behavior.

Reference values from documentation:

```text
current value: 99.9%
target: 100%
```

---

### 2. FBP

**Full name:** Fraud Basis Point  
**Russian meaning:** количество копеек, потерянных клиентами на 100 рублей транзакционного оборота.

Use this metric to estimate client fraud losses relative to transaction volume.

Formula:

```text
FBP = lost fraud amount / transaction volume
```

Interpretation:

```text
FBP shows how many kopecks clients lose per 100 rubles of transactions.
```

Calculation rules:

- calculate for individuals;
- include channels:
  - ДБО;
  - Карты;
  - ВСП;
  - эквайринг;
- exclude credit operations;
- include only missed fraud from category `КПЭ`.

Reference values from documentation:

```text
current value: 0.03
target: 0.05
```

---

### 3. FBP for Self-Transfers

**Full name:** Fraud Basis Point по самопереводам  
**Russian name:** FBP по самопереводам

Use this metric when fraud monitoring warned the client, but the client still confirmed the operation.

Meaning:

```text
Amount of client losses per 100 rubles of transaction volume in cases where fraud monitoring alerted the client and warned about possible fraud.
```

Formula:

```text
self_transfer_FBP = accepted fraud amount / transaction volume
```

Calculation rules:

- calculate for individuals;
- include channels:
  - ДБО;
  - Карты;
  - ВСП;
  - кредиты;
- include only accepted fraud;
- use when the client confirmed the operation despite the fraud-monitoring warning.

Reference values from documentation:

```text
current value: 0.10
target: not specified
```

---

### 4. FP

**Full name:** False Positive  
**Russian name:** ложные сработки

Use this metric to estimate the share of false fraud-monitoring alerts.

Formula:

```text
FP = false positive alerts / all fraud-monitoring alerts
```

Meaning:

```text
FP shows the share of alerts that were not actually fraud among all fraud-monitoring alerts.
```

Calculation rules:

- calculate for channels:
  - ДБО;
  - Карты;
- exclude events without resolution;
- events without resolution are considered a grey zone and must not be included;
- calculate both the general individual-client FP and detailed FP variations.

Required FP variations:

1. General FP for individuals.
2. FP by convenient confirmation channels:
   - ChipPin;
   - HINT.
3. FP by inconvenient confirmation channels:
   - all channels except ChipPin and HINT.
4. Share of false positives by inconvenient confirmation channels among all alerts.

Reference values from documentation:

```text
classic FP current value: 49–50%
classic FP target: less than 49.9%

share of inconvenient confirmations among all alerts current value: 11.4%
share of inconvenient confirmations among all alerts target: 11.53%
```

Behavior patterns:

- FP is lower on weekends than on weekdays;
- FP is lower in January, May, and June due to many holidays;
- FP increases in December because clients make more atypical operations;
- FP increases from the 5th to the 10th day of the month due to salary payments.

---

### 5. AR

**Full name:** Approval Rate  
**Russian meaning:** доля операций, проходящих без остановки фрод-мониторингом.

Use this metric to estimate how often operations pass without being stopped by fraud monitoring.

Formula:

```text
AR = operations without fraud-monitoring stop / all operations
```

Calculation rules:

- calculate by number of events, not by ruble amount;
- currently include only alerts through inconvenient confirmation channels;
- treat ChipPin and HINT alerts as non-blocking because they do not significantly slow down the client operation;
- exclude events that the bank cannot avoid stopping.

Exclude from AR calculation:

- ФИДы;
- ДРОПы;
- blacklists;
- other events that must be mandatorily stopped.

Reference values from documentation:

```text
current value: 99.98%
target: not specified
```

---

### 6. CSI

**Full name:** Customer Satisfaction Index  
**Russian name:** индекс удовлетворенности клиента

Use this metric to estimate client satisfaction with fraud monitoring and related interaction.

Formula:

```text
CSI = average customer survey score
```

Calculation rules:

- calculate from client survey results;
- use the average score given by surveyed clients;
- can be calculated as:
  - overall CSI;
  - CSI by operation confirmation channel.

Reference values from documentation:

```text
current value: 4.5
target: 4.5
```

---

## Fraud Volume Categories

### Prevented Fraud

**Name:** save  
**Also known as:** True Positive

A case is considered prevented fraud if:

- the event is related to a payment, transfer, or cash withdrawal;
- fraud monitoring triggered an alert;
- after confirming operation legitimacy, the bank received direct client feedback;
- the client confirmed an attempted unauthorized operation.

Also include cases where:

- no final resolution was received;
- but the status of the suspended operation did not change.

---

### Missed Fraud

**Name:** lost  
**Also known as:** False Negative

A case is considered missed fraud if:

- the client reported an unauthorized operation;
- the operation happened in a monitored channel;
- the case is not included in the exclusion list below.

Exclude from missed fraud:

- бытовое or non-professional fraud cases;
- cases stopped by fraud monitoring where the client ignored the warning and confirmed the operation;
- transfers made by the client to themselves inside the bank or to another bank;
- cases without actual client loss;
- unsuccessful operations;
- cases manually reviewed by a DPM analyst and recognized as non-fraudulent;
- disputes related to goods or services not received;
- transfers to legitimate organizations where the client later receives compensation;
- operations within accepted bank risk appetite, for example small operations in high-yield segments;
- operations for products not integrated with the fraud-monitoring system.

---

## False Positive Exclusions

Do not treat an alert as false positive when the bank has a strong reason to believe the operation is fraudulent.

Examples:

- recipient details are present in Central Bank restriction lists:
  - ФИДы;
  - ФИДы+;
- there is a fraud complaint against the recipient;
- the recipient was received through regulated information exchange of fraudulent реквизиты;
- the recipient profile has drop-related signs;
- the recipient was classified as a drop by a model verdict.

---

## Central Bank Metrics

Internal DPM metrics may have analogues in Central Bank reporting.

Important rules:

- Central Bank metrics are formed based on form №716-П;
- do not directly compare DPM metrics and Central Bank metrics one-to-one;
- the metrics may be similar in meaning, but their methodologies differ;
- treat any match between internal and Central Bank metrics as conditional unless the exact methodology is provided.

---

## Agent Workflow

When the user asks about fraud-monitoring metrics, follow this workflow.

### Step 1. Identify the requested metric

Determine whether the user is asking about:

- Effectiveness;
- FBP;
- FBP for self-transfers;
- FP;
- AR;
- CSI;
- save;
- lost;
- false positives;
- Central Bank comparison;
- general documentation cleanup.

If the metric is ambiguous, infer it from context. If there is still not enough information, explain the likely interpretation and state the uncertainty.

---

### Step 2. Identify the population and channel

Check whether the request concerns:

- individuals;
- legal entities;
- ДБО;
- Cards;
- ВСП;
- acquiring;
- credits;
- convenient confirmation channels;
- inconvenient confirmation channels.

If no population is specified, default to individuals.

---

### Step 3. Apply inclusion and exclusion rules

Before calculating or interpreting a metric, verify:

- whether credit operations should be excluded or included;
- whether only `КПЭ` should be included;
- whether only accepted fraud should be included;
- whether unresolved events should be excluded;
- whether mandatory stops must be excluded;
- whether the event should be treated as save, lost, or neither.

---

### Step 4. Calculate or explain the metric

If the user provides data, calculate the metric.

If the user does not provide data, explain:

- formula;
- business meaning;
- included channels;
- exclusions;
- interpretation;
- known behavioral patterns.

---

### Step 5. Return an analyst-friendly answer

Prefer clear business language.

Avoid unnecessary technical jargon unless the user asks for implementation details.

Use tables when comparing several metrics.

Use this structure for metric explanations:

```text
Metric:
Meaning:
Formula:
Included:
Excluded:
Current value:
Target:
Interpretation:
Important caveats:
```

---

## Output Templates

### Template: Single Metric Explanation

Use this structure:

```markdown
## <Metric name>

**Meaning:** <business meaning>

**Formula:**

<formula>

**Included in calculation:**

- <included item>

**Excluded from calculation:**

- <excluded item>

**Current value:** <value>  
**Target:** <target or "not specified">

**Interpretation:** <how to read the metric>

**Important caveats:** <methodological caveats>
```

---

### Template: Metric Comparison

Use this structure:

```markdown
| Metric | What it measures | Formula | Included | Excluded | Current value | Target |
|---|---|---|---|---|---:|---:|
| <metric> | <meaning> | <formula> | <included> | <excluded> | <value> | <target> |
```

---

### Template: Case Classification

Use this structure:

```markdown
## Fraud Classification

**Case type:** save / lost / false positive / excluded / uncertain

**Reasoning:**

- <reason 1>
- <reason 2>
- <reason 3>

**Included in metric calculation:** yes / no

**Metric impact:**

- Effectiveness: <impact>
- FBP: <impact>
- FP: <impact>
- AR: <impact>

**Caveats:** <uncertainties or missing data>
```

---

## Quality Checks

Before finalizing the answer, verify:

- the metric name is correct;
- the formula matches the metric;
- the channel scope is correct;
- exclusions are applied;
- save and lost are not mixed up;
- accepted fraud is not incorrectly treated as missed fraud;
- unresolved cases are not included in FP;
- ChipPin and HINT are treated correctly for AR;
- Central Bank metrics are not directly equated with DPM metrics.

---

## Style Rules

Write in Russian unless the user asks otherwise.

Prefer concise, structured explanations.

Use business-facing terminology:

- "выявленное мошенничество";
- "пропущенное мошенничество";
- "ложная сработка";
- "канал подтверждения";
- "операция без остановки";
- "фактические потери клиента".

Avoid vague phrases such as:

- "скорее всего считается как-то так";
- "примерно одно и то же";
- "можно напрямую сравнить с ЦБ".

When uncertain, say explicitly:

```text
По предоставленным данным это нельзя определить однозначно, потому что не хватает <missing field>.
```

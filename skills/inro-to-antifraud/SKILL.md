---
name: intro-to-antifraud
description: 
Используй этот навык, кога тебе необходимо получить обущую информации о деятельности антифрода банка. Здесь ты можешь получить информацию о канал подтверждения, резолюциях и другую бизнес логику
---

# Core domain model

A bank transaction passes through antifraud before the operation is finally allowed, stopped, or sent to a confirmation scenario.

The high-level process is:

1. The bank receives transaction data.
2. The antifraud system enriches the transaction with additional features.
3. Rules and AI scoring models evaluate the risk.
4. The system returns a decision in `policy_action`.
5. If needed, a confirmation scenario starts.
6. The confirmation scenario produces a resolution.
7. The operation is either conducted, stopped, or marked for further analysis.

---

# Role of the Analytics and Statistics team

The Analytics and Statistics team supports the fraud-monitoring system through:

- monitoring KPI metrics and operational indicators;
- maintaining reports and dashboards;
- performing ad-hoc analytical investigations;
- supporting urgent expert analysis;
- interacting with ФинЦЕРТ;
- preparing regulatory statistics and reports for the Bank of Russia;
- evaluating antifraud quality, prevented fraud volume, and rule effectiveness.

---

# Transaction data used by antifraud

At the first stage, antifraud receives the information required to evaluate the operation.

Typical input data includes:

- transaction parameters;
- client data;
- recipient data for P2P operations;
- merchant or торгово-сервисная точка data for acquiring operations;
- channel data;
- device and session data, if available;
- behavioral and historical data;
- technical context of the operation.

The exact set of fields depends on the operation channel and the source system.

---

# Custom facts and feature enrichment

After receiving the base transaction data, antifraud calculates additional features.

These features may include:

- standard custom facts;
- custom facts from ФПДО;
- links between client, recipient, device, account, card, merchant, and other entities;
- AI model outputs;
- historical behavior aggregates;
- risk indicators;
- contextual transaction features.

Use the terms:

- `CF` — custom facts / calculated features;
- `ФПДО` — functional subsystem of additional processing;
- `CF ФПДО` — additional enriched features calculated by ФПДО.

Custom facts are needed because raw transaction parameters are often not enough to detect fraud. They allow rules and models to use broader transaction context.

---

# Antifraud rules

After enrichment, the transaction is checked against antifraud rules.

Rules are risk checks that compare operation parameters and calculated features against known fraud patterns or risk events.

Rules may use:

- client age;
- client income;
- transaction amount;
- transaction time;
- transaction location;
- recipient attributes;
- transaction history;
- client behavior;
- operation channel;
- AI score;
- custom facts;
- links to suspicious entities;
- blacklists and drop accounts.

The full rule system can be understood as a decision tree or rule graph.

A simplified example of a rule:

```text
age >= 65 AND time > 21:00 AND amount >= 10000
```

Each rule has a priority. If several rules trigger, the priority helps determine the main controlling decision.

---

# AI scoring models

AI scoring models are used to make antifraud rules more accurate.

The model score may:

- strengthen a risky rule;
- weaken a rule when the context looks safe;
- help rank the risk level;
- improve precision of fraud detection;
- reduce false positives.

When explaining AI models, do not describe them as a replacement for rules. In this domain, they work together with rules and help refine antifraud decisions.

---

# `policy_action`

`policy_action` is the antifraud system decision for the operation.

It is not the same as a final fraud resolution.

## Possible values

| Value | Meaning | Operational interpretation |
|---|---|---|
| `NULL` | No antifraud rule triggered | The operation is considered legitimate by antifraud and is allowed. |
| `allow` | Whitelisted / pre-approved operation | The operation is allowed because there are factors that reduce the risk. |
| `review` | Risky operation | The operation is paused until client confirmation. |
| `deny` | High-risk operation | The operation is stopped. If the client later confirms, they usually need to repeat the operation. |

## Important distinctions

- `NULL` means no antifraud rule produced a controlling action.
- `allow` means a rule did trigger, but the operation was explicitly allowed.
- `review` means the operation is paused and can continue after confirmation.
- `deny` means the current operation is stopped; after confirmation, a repeated operation may be allowed.

Never treat `NULL` as a resolution. It is the absence of a fraud-monitoring action.

---

# Confirmation logic

If `policy_action = review` or `policy_action = deny`, the system starts an operation confirmation scenario.

General logic:

- For `review`, if the client confirms the operation, it can continue to processing.
- For `deny`, the current operation is stopped. If the client confirms legitimacy, a repeated operation may be allowed through whitening logic.

---

# SLA and technical constraints

Fraud monitoring has strict performance requirements.

Important constraints:

- response time SLA is very strict, around 100 ms;
- transaction throughput can reach tens of thousands of transactions per second;
- if antifraud does not respond within SLA, the operation may be passed to processing;
- if custom facts are not calculated during an incident, operation quality checks degrade.

## CF failure scenarios

There are two important CF failure scenarios.

### Soft degradation

Standard CF are calculated, but CF ФПДО are not calculated.

Consequences:

- complex links and model-related features may be unavailable;
- heavy rules may not work;
- simpler rules may still work;
- antifraud continues operating, but accuracy decreases.

### Hard degradation

CF are not calculated at all.

Consequences:

- operations may pass to processing with `policy_action = NULL`;
- antifraud quality drops significantly;
- this creates risk during high-load incidents;
- BIN attacks are dangerous partly because they can overload antifraud and prevent proper checks.

---

# Operation channels

Bank operations differ by channel.

For individuals, common channels are:

- cards;
- ДБО — дистанционное банковское обслуживание;
- ВСП — bank branches / internal structural divisions;
- acquiring.

Legal entity operations have separate logic, rules, and confirmation processes.

---

# Acquiring operations

Acquiring differs from other individual-client operations.

In acquiring:

- the bank may serve the terminal or merchant;
- the person making the payment may not be the bank’s client;
- the bank may not have enough data to protect that person through full fraud monitoring;
- antifraud logic and available data may differ from card or ДБО operations.

---

# Triggers and confirmation categories

A fraud-monitoring trigger is a paused or specially processed operation.

Triggers can be divided into categories:

1. Triggers that require client confirmation.
2. Triggers that do not require confirmation.
3. Technical or informational triggers.
4. Whitening triggers.

---

# Triggers that cannot be confirmed by the client

Some operations cannot be confirmed by the client. The bank will not conduct them even if the client believes the operation is legitimate.

Examples:

- operations to ФИДs, where transfers are prohibited by the Bank of Russia;
- operations to blacklisted requisites;
- operations to drop accounts or drop-related requisites.

---

# Technical and informational triggers

Some triggers are technical or informational and do not require client confirmation.

When analyzing such cases, do not assume that every trigger means client contact happened.

---

# Whitening rules

Whitening rules usually appear after a previous high-risk trigger.

Typical logic:

1. A client had a trigger with `policy_action = deny`.
2. The client confirmed the operation or passed a confirmation process.
3. To allow the client to repeat the operation without being stopped again, a temporary whitening rule is created.
4. The repeated operation may receive `policy_action = allow`.

Interpretation:

```text
policy_action = 'allow'
```

means that the operation was explicitly allowed by antifraud logic, not simply ignored by antifraud.

---

# Confirmation channels

Use this table when explaining how operations can be confirmed.

| Channel | Typical use case | Approximate volume | Notes |
|---|---|---:|---|
| Chip & Pin | `deny` in card channel | up to 2k/day | Client confirms card and PIN at terminal. |
| Hint Cards | `deny` in card channel | up to 30k/day | Hint shown during card payment. |
| Hint ДБО | `review` in ДБО | up to 100k/day | Hint shown in СБОЛ or digital banking. |
| ЕРКЦ | `deny` in ДБО and card channels | 300–500/day | Contact center, operator call. |
| IVR | `deny` in card channel or `review` in ДБО | up to 30k/day | Interactive voice response, incoming or outgoing calls. |
| ВСП specialist | `review` or `deny` in ДБО | up to 20k/day | Communication with a branch employee. |
| РО / ЗРО | `deny` in ВСП | up to 500/day | Branch specialist scenario, often for clients under influence. |
| ЦПК Бета | `deny` in ДБО and card channels | up to 50/day | Anti-fraud center employee, often for clients under influence. |
| Confirmation by relatives | `deny` in ДБО and card channels | up to 10/day | Used for elderly clients under influence. |
| ГПМ | `deny` in ДБО, ВСП, and card channels | up to 70/day | Most strict scenario for clients likely under external influence. |

The ГПМ scenario is the strictest and is used rarely. It is applied when there is strong reason to believe the client is under someone else’s influence.

---

# Sequential confirmation scenarios

Confirmation scenarios may happen sequentially.

Examples:

- a ВСП employee suspects external influence and redirects the client to ГПМ;
- a client starts confirmation via IVR and then moves to ЕРКЦ;
- an automated scenario fails and the case moves to manual review.

Each confirmation scenario can produce a new resolution.

---

# Resolutions

A resolution is the result of a confirmation scenario after a fraud-monitoring trigger.

A resolution is not the same as `policy_action`.

`policy_action` is the antifraud system’s initial controlling decision.

Resolution is the result after the confirmation or investigation scenario.

---

# Missing resolution

A trigger may have no resolution.

Possible reasons:

- the bank could not contact the client;
- the client did not confirm the operation;
- the client did not reject the operation;
- the automated scenario was not completed.

In reports and dashboards, missing resolution may appear as:

- `NULL`;
- `N`;
- empty value.

Important rule:

Do not interpret missing resolution as a real resolution. It means the resolution is absent.

---

# Resolution types

| Resolution | Meaning | Interpretation |
|---|---|---|
| `G` | Genuine | Legitimate operation. The client confirmed the operation and is not under fraudster influence. |
| `A` | Assume genuine | Probably legitimate operation, but some uncertainty remains. Rare case. |
| `U` | Undefined | The client did not conduct the operation, the operation is no longer relevant, identity is uncertain, or fraud is not confirmed. Operation is not conducted. |
| `S` | Suspect Fraud | Suspected fraud. The client may be under influence, requisites may be suspicious, or other fraud indicators exist. |
| `F` | Fraud | Confirmed fraud. The client confirms fraudster influence or the operation was not performed by the client. |

Operations with resolutions `G` and `A` may be conducted further.

---

# How resolutions are used

The Analytics and Statistics team uses resolutions for:

- antifraud KPI calculation;
- prevented fraud volume estimation;
- blacklist updates;
- fraud labeling for complaint analysis;
- rule quality analysis;
- confirmation channel quality analysis;
- false positive and false negative analysis.

---

# Legal entity antifraud

Antifraud for legal entities is a separate system with its own processes, rules, and logic.

Important differences:

- all legal entity transactions are paused for 2 hours before funds transfer;
- triggered operations may be sent to ОВПТ;
- triggered operations may be sent to ЦПК Гамма;
- confirmation and investigation differ from individual-client processes.

---

# ОВПТ

ОВПТ means department of verification of suspicious transactions.

It acts as a contact-center-like process for legal entities.

Typical features:

- receives events with `OVPT` rule mask;
- contacts clients, usually through outgoing calls;
- verifies suspicious transactions;
- assigns a resolution after speaking with the client.

---

# ЦПК Гамма

ЦПК Гамма handles offline case review for legal entity antifraud.

Cases may arrive there:

- directly after an antifraud trigger;
- after ОВПТ if the client could not be reached;
- when the case is complex or requires deeper review.

ЦПК Гамма has two support lines:

| Line | Purpose |
|---|---|
| 1st line | Review ОВПТ cases and more complex rules. |
| 2nd line | Review more straightforward rules. |

If the result is positive, the transaction is conducted.

---

# How to analyze an antifraud case

When the user asks to analyze a trigger, event, transaction, or blocked operation, follow this workflow.

## Step 1. Identify the operation

Extract:

- event ID;
- client ID;
- operation date and time;
- amount;
- channel;
- operation type;
- recipient or merchant;
- source system;
- legal entity or individual client flag.

## Step 2. Identify antifraud decision

Find and interpret:

- `policy_action`;
- triggered rule or rule mask;
- rule priority;
- whether this was a normal trigger, technical trigger, or whitening rule;
- whether CF were calculated.

## Step 3. Determine channel-specific logic

Check whether the operation belongs to:

- cards;
- ДБО;
- ВСП;
- acquiring;
- legal entity antifraud.

Use channel-specific confirmation and interpretation rules.

## Step 4. Check confirmation scenario

If `policy_action` is `review` or `deny`, determine:

- whether confirmation was required;
- which confirmation channel was used;
- whether there were sequential scenarios;
- whether the client was reached;
- whether the scenario produced a resolution.

## Step 5. Interpret resolution

If resolution exists, map it as:

- `G` or `A` — operation is legitimate or probably legitimate;
- `U` — undefined, operation is not conducted, fraud not confirmed;
- `S` — suspected fraud;
- `F` — confirmed fraud.

If resolution is missing, state clearly that there is no final confirmation result.

## Step 6. Explain likely cause

Provide a concise explanation:

- why antifraud reacted;
- whether the operation looked typical or atypical;
- whether the cause is likely transaction behavior, recipient risk, channel risk, rule logic, technical degradation, or client influence;
- what data supports the conclusion;
- what uncertainty remains.

---

# Recommended answer format for case analysis

When analyzing a transaction, answer in this structure:

```markdown
## Краткий вывод

<1–3 предложения: операция обычная / подозрительная / недостаточно данных>

## Что произошло

- Операция:
- Канал:
- Клиент:
- Получатель / ТСТ:
- Сумма:
- Дата и время:
- `policy_action`:
- Резолюция:

## Почему сработал антифрод

<Объяснение причины сработки>

## Какой сценарий подтверждения был запущен

<Канал подтверждения, если есть>

## Как интерпретировать резолюцию

<Расшифровка G/A/U/S/F или указание, что резолюции нет>

## Итоговая оценка

<Была ли операция похожа на обычную активность клиента, что могло привести к блокировке, что нужно проверить дополнительно>
```

---

# Important reasoning rules

Always distinguish:

- `policy_action` from resolution;
- `NULL policy_action` from `allow`;
- missing resolution from `U`;
- technical trigger from fraud trigger;
- individual-client antifraud from legal-entity antifraud;
- acquiring from normal client card operations;
- current stopped operation from repeated allowed operation after whitening.

Do not claim fraud is confirmed unless there is a resolution `F` or explicit evidence.

Do not claim the operation is legitimate unless there is `G`, `A`, `allow`, or enough contextual evidence.

If data is incomplete, say what is missing.

---

# Common mistakes to avoid

Avoid these mistakes:

1. Treating `NULL` as a resolution.
2. Treating `allow` and `NULL` as the same thing.
3. Assuming every `deny` means confirmed fraud.
4. Assuming every trigger requires client confirmation.
5. Forgetting that some triggers cannot be confirmed by the client.
6. Ignoring CF calculation failures during incidents.
7. Applying individual-client confirmation logic to legal entity operations.
8. Treating acquiring as a normal individual-client antifraud case.
9. Ignoring sequential confirmation scenarios.
10. Saying a transaction was conducted without checking `policy_action`, confirmation, and resolution.

---

# Glossary

| Term | Meaning |
|---|---|
| Антифрод | Fraud-monitoring system that detects suspicious banking operations. |
| ФМ | Fraud monitoring. |
| ДПМ | Anti-fraud department / fraud prevention department context. |
| CF | Custom facts, calculated features used by antifraud. |
| ФПДО | Functional subsystem of additional processing. |
| CF ФПДО | Additional enriched features calculated by ФПДО. |
| `policy_action` | Antifraud decision for the operation. |
| `review` | Operation is paused for confirmation. |
| `deny` | Operation is stopped. |
| `allow` | Operation is explicitly allowed by antifraud logic. |
| `NULL` | No antifraud rule triggered or no controlling action was produced. |
| Сработка | Triggered antifraud event or paused operation. |
| Резолюция | Result of operation confirmation or investigation scenario. |
| `G` | Genuine, legitimate operation. |
| `A` | Assume genuine, probably legitimate operation. |
| `U` | Undefined, fraud not confirmed but operation not conducted. |
| `S` | Suspect Fraud, suspected fraud. |
| `F` | Fraud, confirmed fraud. |
| ДБО | Remote banking / digital banking channel. |
| ВСП | Bank branch / internal structural division. |
| ТСТ | Merchant / торгово-сервисная точка. |
| ЕРКЦ | Contact center scenario. |
| IVR | Interactive voice response scenario. |
| ГПМ | Strict fraud-prevention specialist scenario for clients under influence. |
| ОВПТ | Department for verification of suspicious transactions for legal entities. |
| ЦПК Гамма | Offline legal-entity antifraud case review unit. |

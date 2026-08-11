# StockAnalyzer Specification

**Status:** Proposed V1 specification

**Date:** 2026-08-11

**Product type:** Local Python command-line application

**Primary output:** Professionally formatted equity research stock sheet

**Target market:** Fundamental investors and analysts researching US SEC-reporting public companies

## 1. Executive Summary

StockAnalyzer creates a reproducible equity research package for a US-listed company and converts that package into a professional stock sheet through exactly one final LLM execution.

The application separates evidence collection from interpretation:

1. Python code resolves the issuer, downloads public source documents, extracts structured facts, normalizes periods and units, computes ratios and comparisons, and validates the research package deterministically.
2. The application freezes the package in a manifest with source URLs, accession numbers, retrieval timestamps, hashes, and calculation lineage.
3. One LLM execution receives only the frozen package and a versioned output contract. It writes a structured analysis response.
4. Deterministic Python code validates and renders the response into Markdown and HTML. PDF and XLSX are optional renderings of the same canonical content.

The V1 free-tier implementation uses:

- SEC EDGAR submissions, filings, and XBRL Company Facts as the authoritative source for issuer identity, annual reports, financial statements, shares, filing metadata, sector proxy, and exceptional-item evidence;
- Alpha Vantage free-tier daily adjusted prices for historical company and benchmark prices, cached permanently to stay within the current limit of 25 requests per day;
- FRED, with a free API key, for optional macroeconomic series;
- local deterministic calculation and document processing libraries;
- one user-configured subscription-authenticated or local LLM command for final synthesis, with no API-key-backed LLM required.

The product is research tooling, not investment advice. It preserves every material source and clearly labels reported, calculated, inferred, estimated, unavailable, and LLM-authored content.

## 2. Goals

StockAnalyzer shall:

1. Generate a decision-useful stock sheet from public evidence for one issuer at a time.
2. Include issuer background, sector and industry, annual and quarterly fundamentals, earnings, cash flow, balance-sheet strength, capital allocation, exceptional items, valuation, price performance, peers, market context, risks, catalysts, and source citations.
3. Obtain and transform as much data as practicable deterministically.
4. Preserve the annual reports and other filings used in the analysis.
5. Make every displayed number traceable to a filing fact, market-data observation, user input, or explicit formula.
6. Use exactly one LLM execution after deterministic collection and validation complete.
7. Produce repeatable results from a frozen evidence package.
8. Operate at no mandatory data-provider cost for light individual use.
9. Fail visibly when evidence is incomplete or contradictory rather than silently inventing or substituting values.

## 3. Non-Goals

V1 does not:

- provide real-time or intraday prices;
- execute trades, manage portfolios, or issue personalized investment advice;
- forecast prices through a machine-learning model;
- promise complete coverage of foreign private issuers, funds, banks, insurers, business development companies, master limited partnerships, pre-revenue issuers, or issuers without usable SEC XBRL history;
- reproduce proprietary analyst consensus, earnings estimates, ratings, target prices, transcripts, news, or paywalled research;
- scrape websites whose terms prohibit automated collection;
- treat LLM output as a source of facts;
- calculate a single opaque investment score;
- guarantee that XBRL tags are economically comparable without validation;
- permit the final LLM to fetch sources, call tools, run calculations, or edit the evidence package.

## 4. Users and Primary Use Case

### 4.1 Primary user

An experienced individual investor or analyst researching US SEC-reporting operating companies.

### 4.2 Primary workflow

```text
configure identity and optional free keys
    -> analyze ticker or CIK at an explicit as-of date
    -> inspect deterministic validation report
    -> execute one final LLM synthesis
    -> open stock sheet and evidence package
```

### 4.3 Example

```bash
stockanalyzer configure --sec-user-agent "Ed Research ed@example.com"
stockanalyzer analyze MSFT --as-of 2026-08-10 --years 5 --quarters 8
```

The command creates a versioned run directory and does not overwrite a prior run.

## 5. Product Principles

### 5.1 Evidence before narrative

The application completes acquisition, parsing, normalization, calculation, and validation before invoking the LLM.

### 5.2 Point-in-time integrity

Only information publicly available at or before `as_of` may enter the package. Filing acceptance time, not fiscal period end, controls availability. Price observations must be on or before `as_of`.

### 5.3 Restatement awareness

The application retains all facts and filing references. It selects the latest fact filed by `as_of` for a given fiscal period and records whether that value restates an earlier filing.

### 5.4 No silent imputation

Missing facts remain null. Derived fallbacks are permitted only when defined by a named formula, validated, labeled `derived`, and accompanied by lineage.

### 5.5 Deterministic authority

Python-generated tables, calculations, citations, and charts are authoritative. The LLM may explain them but may not change their values.

### 5.6 Provider isolation

Every external source implements a provider interface. Raw responses are cached unchanged. Normalized records do not depend on provider-specific field names.

## 6. Source Strategy and Free-Tier Feasibility

### 6.1 Required sources

| Need | Default source | Authentication | V1 use |
|---|---|---:|---|
| Ticker, CIK, name, exchange | SEC ticker association file | None | Issuer resolution |
| Filing history and issuer metadata | SEC Submissions API | None | Forms, SIC, fiscal year end, former names |
| Reported financial facts | SEC XBRL Company Facts API | None | Statements and KPI candidates |
| Annual and quarterly reports | SEC EDGAR Archives | None | 10-K, 10-Q, amendments, exhibits where selected |
| Filing-native statement structure | Filing Inline XBRL and filing XBRL files | None | Tag mapping, dimensions, presentation context |
| Historical adjusted prices | Alpha Vantage | Free key | Issuer and benchmark total-return inputs |
| Macro context | FRED | Free key | Optional rates, inflation, unemployment, recession series |
| SIC title | SEC filing metadata/static mapping | None | Industry classification |

### 6.2 SEC access contract

The client shall:

- send a declared `User-Agent` containing an application or organization name and contact email;
- remain below the SEC's published maximum of 10 requests per second, with a default application limit of 2 requests per second;
- use conditional requests when supported, local immutable caching, exponential backoff with jitter, and bounded retries;
- prefer bulk archives when operating on many issuers;
- never bypass access controls;
- record URL, response headers, retrieval time, status, content type, byte count, and SHA-256 hash;
- preserve raw SEC responses without semantic alteration.

SEC's public APIs require no API key. The application shall not describe them as having an uptime, completeness, or support guarantee.

### 6.3 Market-price contract

Alpha Vantage is the default V1 price adapter because its free service currently covers most datasets with a limit of 25 requests per day. The adapter shall use daily adjusted data, cache complete responses permanently, and make at most one refresh request per symbol per UTC day.

Consequences:

- a normal single-company run uses two to six market-data requests: issuer, broad benchmark, sector benchmark, and up to three explicitly selected peers;
- peer comparison defaults to fundamental comparisons when the remaining daily request budget cannot support peer price downloads;
- price data is end-of-day and may be delayed;
- a run without an Alpha Vantage key remains valid but omits price-derived valuation and return fields unless the user imports prices;
- provider errors or limit messages are hard failures for required price fields and warnings when price analysis is configured as optional.

The normalized price-provider interface permits later replacement with a licensed provider. An imported CSV adapter shall be available for users who already possess lawful market data.

### 6.4 Macro contract

FRED is optional. When enabled, the user supplies a free FRED API key. The default US macro set is configuration, not code:

- effective federal funds rate;
- 10-year Treasury yield;
- 10-year minus 2-year Treasury spread;
- CPI year-over-year change;
- unemployment rate;
- NBER recession indicator.

The package shall retain FRED series metadata, observation date, vintage or real-time bounds, source notes, and copyright indicators. A redistribution mode shall exclude series whose terms do not permit the intended use.

### 6.5 Sector, industry, and peers

V1 uses the issuer's SEC SIC code and SIC title as the authoritative industry classification. Because SEC SIC is not equivalent to commercial GICS classifications:

- output labels it `SEC SIC industry`, never `GICS sector`;
- a versioned local mapping may map SIC to a broad analytical sector and sector ETF;
- mapped values are labeled `mapped` and cite the mapping version;
- users may override sector, industry, benchmark, and peer set in run configuration;
- peer membership is never presented as an SEC fact.

Automatic peer discovery shall be deterministic: eligible US operating companies sharing the most specific configured SIC prefix, then ranked by latest computable market capitalization. V1 caps the candidate set before price retrieval and selects at most five peers. The full selection trace is saved.

### 6.6 Source precedence

For conflicting values, precedence is:

1. a filing's own Inline XBRL instance and presentation for that filing;
2. SEC Company Facts for cross-filing history;
3. values deterministically derived from authoritative facts;
4. user-supplied values with explicit provenance;
5. external price or macro providers;
6. LLM commentary, which never supplies authoritative values.

## 7. Command-Line Interface

### 7.1 Commands

```text
stockanalyzer configure [options]
stockanalyzer collect <TICKER|CIK> [run options]
stockanalyzer validate <RUN_DIRECTORY>
stockanalyzer synthesize <RUN_DIRECTORY> [--force]
stockanalyzer analyze <TICKER|CIK> [run options]
stockanalyzer render <RUN_DIRECTORY> [--format markdown|html|pdf|xlsx]
stockanalyzer sources <RUN_DIRECTORY>
stockanalyzer cache status|prune [options]
```

`analyze` is the composed operation `collect -> validate -> synthesize -> render`. It invokes the LLM once only. The separate commands support inspection, recovery, offline re-rendering, and testability.

### 7.2 Run options

```text
--as-of YYYY-MM-DD             Required logically; defaults to current local date
--years INTEGER                Annual history, default 5, range 3..10
--quarters INTEGER             Quarterly history, default 8, range 4..20
--benchmark SYMBOL             Default SPY
--sector-benchmark SYMBOL      Default from versioned SIC mapping
--peer SYMBOL                  Repeatable explicit peer override
--max-peers INTEGER            Default 5, range 0..10
--price-provider NAME          alpha-vantage|csv|none
--macro-provider NAME          fred|none
--currency CODE                Display currency; default issuer reporting currency
--output-root PATH             Default ./output
--offline                      Use cache only; make no network calls
--strict                       Treat coverage warnings as failures
--llm-provider NAME            Configured subscription/local CLI adapter
--model NAME                   Optional provider-specific model override
```

### 7.3 Exit codes

| Code | Meaning |
|---:|---|
| 0 | Command completed and all required output contracts passed |
| 1 | Operational failure: network, provider, parsing, rendering, or LLM execution |
| 2 | Invalid command or configuration |
| 3 | Evidence validation failed; LLM was not invoked |
| 4 | LLM output failed schema or citation validation |
| 5 | Required source unavailable under offline or free-tier constraints |

## 8. Run Lifecycle and State Machine

```text
CREATED
  -> COLLECTING
  -> NORMALIZING
  -> CALCULATING
  -> VALIDATING
  -> READY_FOR_SYNTHESIS
  -> SYNTHESIZING
  -> SYNTHESIZED
  -> RENDERING
  -> COMPLETE
```

Any stage may transition to `FAILED`. A failed run is immutable except for append-only logs. Resume creates a new attempt record within the same run and skips valid content-addressed artifacts.

The synthesis guard shall refuse execution unless:

- state is `READY_FOR_SYNTHESIS`;
- validation has no errors;
- the input manifest hash matches the validated hash;
- no successful LLM attempt already exists, unless `--force` is specified;
- the configured LLM executable resolves locally.

`--force` creates a new synthesis attempt and never overwrites the previous response. A standard `analyze` execution still performs exactly one attempt.

## 9. Output Layout

```text
output/<CIK>/<AS_OF>/<RUN_ID>/
  run.json
  manifest.json
  validation.json
  sources.md
  raw/
    sec/
    prices/
    macro/
  filings/
    <accession>/
      filing.html
      filing.txt
      filing-metadata.json
      xbrl/
  normalized/
    issuer.json
    filings.json
    facts.parquet
    periods.json
    prices.parquet
    macro.parquet
    peers.json
    exceptional-items.json
  calculated/
    financials.json
    metrics.json
    comparisons.json
    charts.json
  research-package/
    package.json
    package.md
    llm-prompt.md
  llm/
    request.json
    stdout.txt
    stderr.txt
    response.json
  report/
    StockSheet.md
    StockSheet.html
    assets/
```

PDF and XLSX are generated only when requested. Raw and normalized artifacts are retained even if synthesis fails.

## 10. Deterministic Collection Pipeline

### 10.1 Issuer resolution

1. Normalize input ticker to uppercase or CIK to ten digits.
2. Resolve ticker through the cached SEC ticker association file.
3. Reject ambiguous ticker mappings unless `--cik` resolves the ambiguity.
4. Fetch SEC submissions for the CIK.
5. Capture legal name, former names, exchanges, tickers, SIC, fiscal year end, state of incorporation, addresses, and entity type where present.
6. Confirm that the requested ticker belongs to the resolved CIK as of collection time; record limitations because the SEC association file is not guaranteed complete.

### 10.2 Filing selection

The filing selector shall consider filings accepted on or before `as_of`.

Default forms:

- annual: `10-K`, `10-K/A`, `20-F`, `20-F/A`, `40-F`, `40-F/A`;
- quarterly: `10-Q`, `10-Q/A`;
- material events: `8-K`, `8-K/A`, limited to configured item numbers and the lookback period;
- proxy: latest `DEF 14A` when executive compensation or ownership context is enabled.

V1 acceptance coverage is US domestic operating companies filing `10-K` and `10-Q`. Other forms are collected when configured but may produce a coverage warning.

For each selected filing, download the filing index, primary document, complete submission text, and available XBRL instance/presentation/calculation/label files. Save accession number, filing date, acceptance datetime, period of report, form, amendment flag, primary document, and URLs.

### 10.3 Document text extraction

Deterministic extraction shall:

- preserve the original filing;
- parse HTML with a non-executing parser;
- remove scripts, styles, hidden XBRL metadata duplication, navigation, and repeated whitespace;
- retain headings, tables, page anchors where available, and Inline XBRL fact identifiers;
- identify 10-K sections using filing structure and conservative heading rules;
- produce bounded excerpts for Business, Risk Factors, MD&A, financial statements, footnotes, controls, legal proceedings, and selected 8-K items;
- record character offsets and source document anchors for every excerpt.

The extractor shall not summarize prose. If section detection confidence is below its configured threshold, the complete cleaned filing text is retained and the package records the section as unresolved.

### 10.4 XBRL ingestion

The system shall ingest Company Facts for longitudinal discovery and filing-native XBRL for selected filing verification.

Each fact record includes:

```text
entity_cik, taxonomy, concept, label, description, unit,
value, decimals, start_date, end_date, instant_date,
fiscal_year, fiscal_period, form, filed_date, acceptance_datetime,
accession, frame, dimensions, source_url, source_hash
```

Facts with dimensions are retained. Consolidated statement metrics prefer facts with no segment dimensions. Segment analysis uses explicitly recognized axes and members and never adds overlapping members without a reconciliation rule.

### 10.5 Period normalization

The period engine shall classify:

- instants;
- fiscal quarters;
- fiscal year-to-date durations;
- fiscal years;
- trailing twelve months.

Classification uses exact dates, duration, fiscal year end, `fp`, `fy`, form, frame, and filing context. Calendar assumptions alone are insufficient.

For flows, standalone Q2 and Q3 values may be derived as current year-to-date less prior year-to-date only when units, taxonomy concept, dimensions, and context are compatible. Derived quarters are labeled and retain both operands.

TTM equals the sum of the latest four validated standalone fiscal quarters. It shall not mix reported and derived quarters when the validation policy forbids it.

### 10.6 Canonical concept mapping

A versioned YAML mapping registry shall define:

- canonical metric name;
- accepted taxonomy concepts in priority order;
- statement type;
- instant or duration behavior;
- permitted units;
- sign convention;
- aggregation behavior;
- industry applicability;
- fallback formula;
- validation tolerances.

Issuer extension concepts may be mapped only when their filing presentation parent, calculation relationships, labels, period behavior, and historical consistency support the mapping. Automatic mappings below threshold remain unmapped and are included as candidates for the final LLM only as evidence, never as canonical numbers.

### 10.7 Required canonical financial metrics

#### Income statement

- revenue;
- cost of revenue where reported;
- gross profit;
- research and development;
- selling, general, and administrative expense;
- operating income;
- interest expense and interest income;
- income before tax;
- income tax expense;
- net income attributable to common shareholders;
- basic and diluted EPS;
- basic and diluted weighted-average shares;
- stock-based compensation when disclosed;
- depreciation and amortization when disclosed.

#### Balance sheet

- cash and cash equivalents;
- short-term investments;
- accounts receivable;
- inventory;
- current assets and current liabilities;
- goodwill and intangible assets;
- total assets;
- short-term and long-term debt;
- operating lease liabilities when available;
- total liabilities;
- common equity;
- noncontrolling interests;
- common shares outstanding.

#### Cash flow

- cash from operations;
- capital expenditures;
- acquisitions net of cash acquired;
- proceeds from and repayments of debt;
- common share issuance;
- share repurchases;
- dividends paid;
- investing cash flow;
- financing cash flow;
- effect of exchange rates;
- net change in cash.

Null coverage is acceptable. Fabricated zeroes are prohibited.

## 11. Exceptional Items

### 11.1 Definition

An exceptional item is a material income-statement, balance-sheet, cash-flow, or per-share effect that management, the filing structure, or deterministic rules identify as unusual, nonrecurring, non-operating, restructuring-related, impairment-related, acquisition-related, disposal-related, litigation-related, disaster-related, tax-related, accounting-change-related, or otherwise important to interpreting normalized performance.

“Exceptional” does not mean automatically excluded. Recurring restructuring, stock compensation, acquisition costs, and litigation may be economically recurring.

### 11.2 Deterministic candidate detection

Candidates are assembled from:

- configured US-GAAP concepts, including impairment, restructuring, gain/loss on sale, discontinued operations, litigation, debt extinguishment, and unusual tax concepts;
- issuer extension labels matching versioned conservative patterns;
- material 8-K items;
- filing tables and footnotes whose headings match the controlled taxonomy;
- differences between GAAP and company-presented non-GAAP reconciliations, when a reconciliation is explicitly filed;
- period-over-period residuals that exceed configured materiality thresholds, flagged for review but not classified automatically.

### 11.3 Exceptional-item record

```json
{
  "id": "EI-2025-001",
  "period": "FY2025",
  "category": "restructuring",
  "description_reported": "...",
  "pretax_amount": null,
  "after_tax_amount": null,
  "eps_effect": null,
  "cash_effect": null,
  "cash_timing": "current|future|noncash|mixed|unknown",
  "statement_locations": ["income_statement", "cash_flow"],
  "management_treatment": "excluded_from_non_gaap|included|not_stated",
  "deterministic_classification": "candidate|confirmed",
  "recurrence_evidence": [],
  "sources": [],
  "confidence": 0.0
}
```

Amounts remain null unless explicitly reported or deterministically derivable. The LLM may discuss recurrence and analytical significance but may not invent an adjustment.

### 11.4 Adjusted metrics

The application shall not create “adjusted earnings” from prose alone. It may calculate adjusted metrics only from a machine-readable adjustment set whose components, signs, tax treatment, and sources are explicit.

Both GAAP and adjusted results must be shown. Adjusted values shall include a reconciliation table and shall never replace GAAP values in source tables.

## 12. Deterministic Calculations

All formulas operate on canonical metrics and emit value, period, unit, formula identifier, operands, source lineage, and status.

### 12.1 Earnings and growth

```text
revenue_growth = revenue_t / revenue_t-1 - 1
eps_growth = diluted_eps_t / diluted_eps_t-1 - 1
gross_margin = gross_profit / revenue
operating_margin = operating_income / revenue
net_margin = net_income_common / revenue
effective_tax_rate = income_tax_expense / income_before_tax
```

Growth is null when the denominator is zero or sign changes make the percentage misleading. The report then displays the absolute change.

### 12.2 Cash flow

```text
free_cash_flow = cash_from_operations - capital_expenditures
fcf_margin = free_cash_flow / revenue
cash_conversion = cash_from_operations / net_income_common
fcf_conversion = free_cash_flow / net_income_common
owner_cash_return = dividends_paid + share_repurchases - common_share_issuance
```

Capital expenditure is stored as a positive analytical outflow regardless of source sign.

### 12.3 Balance sheet and returns

```text
net_debt = short_term_debt + long_term_debt - cash - short_term_investments
current_ratio = current_assets / current_liabilities
debt_to_equity = total_debt / common_equity
roa = net_income / average(total_assets)
roe = net_income_common / average(common_equity)
roic = nopat / average(invested_capital)
nopat = operating_income * (1 - normalized_tax_rate)
invested_capital = debt + equity - cash_and_excess_investments
```

ROIC components and the excess-cash policy are displayed because no universal definition exists.

### 12.4 Per-share and dilution

```text
revenue_per_share = revenue / diluted_weighted_average_shares
fcf_per_share = free_cash_flow / diluted_weighted_average_shares
dilution_rate = diluted_weighted_average_shares_t / diluted_weighted_average_shares_t-1 - 1
```

### 12.5 Valuation

Valuation uses the latest eligible closing price on or before `as_of` and the latest share count publicly available by `as_of`.

```text
market_cap = price * shares_outstanding
enterprise_value = market_cap + total_debt + preferred_equity
                   + noncontrolling_interest - cash - short_term_investments
price_to_earnings = market_cap / ttm_net_income_common
price_to_sales = market_cap / ttm_revenue
price_to_fcf = market_cap / ttm_free_cash_flow
ev_to_sales = enterprise_value / ttm_revenue
ev_to_ebit = enterprise_value / ttm_operating_income
fcf_yield = ttm_free_cash_flow / market_cap
earnings_yield = ttm_net_income_common / market_cap
dividend_yield = trailing_12m_common_dividends / market_cap
```

Negative or zero denominators yield null multiples and an explanatory status, not negative valuation multiples.

### 12.6 Returns and comparisons

The application calculates split- and dividend-adjusted total returns where the provider supplies adjusted data:

- 1 month, 3 months, year to date, 1 year, 3 years annualized, and 5 years annualized;
- excess return against broad and sector benchmarks;
- annualized volatility from daily log returns;
- maximum drawdown;
- rolling 36-month beta when at least 504 overlapping observations exist.

Each comparison uses aligned trading dates. Missing observations are not forward-filled across more than the configured tolerance.

Peer comparisons include available growth, margins, cash conversion, leverage, returns on capital, valuation, and price performance. Median and percentile ranks require at least three valid peers and show sample size.

## 13. Research Package

### 13.1 Package purpose

`package.json` is the sole machine-readable input to final synthesis. `package.md` is a human-readable equivalent. Both are generated from the same normalized objects and share a manifest hash.

### 13.2 Package contents

1. Run identity, as-of date, software version, mapping versions, and manifest hash.
2. Issuer profile and classification provenance.
3. Selected filing inventory.
4. Financial tables with statuses and citations.
5. Exceptional-item candidates and reconciliations.
6. Calculated metrics and exact formulas.
7. Price, benchmark, macro, and peer comparisons.
8. Filing excerpts for business model, segments, strategy, risks, MD&A drivers, liquidity, capital allocation, commitments, and material events.
9. Coverage matrix, warnings, contradictions, and unresolved mappings.
10. Citation catalog.
11. Required response schema and narrative constraints.

### 13.3 Bounded input

The package builder enforces a configured character or token budget before LLM execution. It prioritizes:

1. contracts and validation warnings;
2. current financial tables and exceptional items;
3. current annual report excerpts;
4. current quarterly report and material 8-K excerpts;
5. historical trends;
6. peer and macro context.

Truncation occurs only at excerpt boundaries and is recorded. Numeric tables and source metadata are never truncated silently.

## 14. Single LLM Synthesis Contract

### 14.1 Execution boundary

The LLM is invoked once per normal run after deterministic validation. The adapter executes a configured subscription-authenticated CLI or local model process. It shall not use an API-key-backed generation path by default.

The process receives:

- a versioned system/task prompt;
- the frozen research package;
- a JSON Schema for the response;
- no network access or tool authorization where the provider supports isolation.

Temperature shall be zero or the provider's lowest deterministic setting. Model name, CLI version, command arguments, start/end times, exit code, stdout, stderr, input hash, and output hash are retained.

### 14.2 LLM responsibilities

The LLM shall:

- explain the business model and reported performance;
- identify material earnings and cash-flow drivers;
- assess the recurrence and analytical meaning of exceptional items using supplied evidence;
- describe balance-sheet resilience and capital allocation;
- compare the company with supplied benchmarks and peers;
- identify evidence-supported risks and catalysts;
- distinguish fact from interpretation;
- cite every material factual assertion using supplied citation IDs;
- identify unresolved questions and data limitations;
- return JSON matching the schema.

### 14.3 Prohibited LLM behavior

The LLM shall not:

- introduce facts, prices, estimates, peers, sources, or calculations absent from the package;
- browse, request a second model pass, or call tools;
- alter deterministic numbers;
- provide buy, sell, or hold instructions;
- invent management guidance or consensus estimates;
- classify an exceptional item as nonrecurring solely because management excludes it;
- emit HTML, Markdown tables, or charts outside schema fields;
- conceal conflicting or missing evidence.

### 14.4 Response schema

The top-level response contains:

```json
{
  "schema_version": "1.0",
  "company_snapshot": {},
  "investment_summary": {},
  "business_and_industry": {},
  "earnings_analysis": {},
  "cash_flow_analysis": {},
  "balance_sheet_and_capital_allocation": {},
  "exceptional_items_analysis": [],
  "valuation_and_market_comparison": {},
  "peer_comparison": {},
  "risks": [],
  "catalysts": [],
  "questions_for_further_research": [],
  "limitations": [],
  "citations_used": []
}
```

Each narrative claim object contains `text`, `citation_ids`, and `claim_type` (`fact`, `calculation`, or `interpretation`). Interpretations cite the evidence from which they arise.

### 14.5 Response validation

Python shall reject the response if:

- it is not valid JSON or violates schema;
- any citation ID is absent from the package;
- any copied numeric field conflicts with its deterministic source beyond display rounding;
- a required section is absent;
- prohibited recommendation language appears;
- limits on field length or item count are exceeded.

V1 does not automatically repair invalid output with another LLM call. It saves the failed response and exits with code 4. A user may explicitly start a new synthesis attempt after inspecting the failure.

## 15. Professional Stock Sheet Contract

### 15.1 Canonical rendering

The report renderer combines deterministic data components with validated LLM narrative. Markdown is canonical; HTML is the primary professional presentation format.

### 15.2 Required report order

1. Cover and identity
2. Executive snapshot
3. Investment summary
4. Business model, segments, sector, and industry
5. Five-year annual financial summary
6. Eight-quarter earnings trend
7. Cash-flow quality and conversion
8. Balance sheet and capital allocation
9. Exceptional items and GAAP-to-adjusted reconciliation
10. Valuation
11. Share-price and benchmark performance
12. Peer comparison
13. Risks and catalysts
14. Questions and limitations
15. Methodology, formulas, and source index

### 15.3 Executive snapshot fields

- legal name, ticker, exchange, CIK;
- as-of date and latest price date;
- SEC SIC industry and mapped analytical sector;
- market capitalization and enterprise value;
- latest fiscal-year and TTM revenue, operating income, net income, EPS, cash from operations, and free cash flow;
- revenue growth, operating margin, FCF margin, net debt, ROIC, and dilution;
- P/E, EV/sales, EV/EBIT, P/FCF, FCF yield, and dividend yield where meaningful;
- latest filing date and next known fiscal period, without predicting an earnings date.

### 15.4 Presentation rules

- Use an institutional, print-safe layout with restrained typography and color.
- Use tabular numerals, explicit currencies, units, periods, and scale labels.
- Show negative values in parentheses and missing values as an em dash.
- Never render null as zero.
- Distinguish reported, derived, adjusted, estimated, and unavailable values visually and in accessible text.
- Include source markers adjacent to material narrative and table headings.
- Repeat the ticker, as-of date, page number, and confidentiality/disclaimer footer on printed pages.
- Meet WCAG 2.2 AA contrast for HTML.
- Avoid red/green-only encoding.
- Render charts from deterministic chart specifications, not LLM-produced images.

### 15.5 Charts

Required when data coverage permits:

- revenue and operating margin by fiscal year;
- diluted EPS and exceptional EPS effects;
- cash from operations, capital expenditure, and free cash flow;
- net debt and share count;
- indexed total return versus broad and sector benchmarks;
- valuation compared with peer median.

Every chart includes period, unit, source note, and accessible tabular fallback.

## 16. Data Quality and Validation

### 16.1 Severity

- `error`: output would be misleading or contract-invalid; synthesis blocked.
- `warning`: output can proceed with an explicit limitation.
- `info`: provenance or coverage note.

### 16.2 Required validations

- resolved CIK and ticker consistency;
- filing accepted by `as_of`;
- unique accession and source hashes;
- compatible units and dimensions;
- fiscal-period continuity and non-overlap;
- duplicate-fact resolution trace;
- balance sheet equation within configured tolerance;
- cash-flow reconciliation within configured tolerance;
- gross profit and operating-income formula cross-checks where components exist;
- EPS/net-income/share relationship within rounding tolerance;
- current and prior fact/restatement detection;
- TTM contains exactly four compatible quarters;
- price date is on or before `as_of`;
- benchmark return windows share aligned observations;
- every calculated value has complete operand lineage;
- every report citation resolves to a cached artifact or source URL;
- LLM package matches the validated manifest hash.

### 16.3 Coverage grades

Coverage is reported by domain, not collapsed into one quality score:

| Domain | Complete | Partial | Insufficient |
|---|---|---|---|
| Identity | All required issuer fields | Noncritical metadata absent | Issuer ambiguous |
| Annual fundamentals | At least 5 compatible years | 3-4 years or some null metrics | Fewer than 3 years |
| Quarterly fundamentals | 8 compatible quarters | 4-7 quarters | Fewer than 4 quarters |
| Cash flow | CFO and capex validated | Derived or incomplete components | FCF unavailable |
| Exceptional items | Candidates and sources resolved | Unquantified candidates | Source ambiguity blocks interpretation |
| Market comparison | Issuer plus two benchmarks | Issuer only or short history | Price unavailable |
| Peers | At least 3 valid peers | 1-2 peers | No valid peers |

Strict mode requires `Complete` for identity and annual fundamentals and at least `Partial` elsewhere.

## 17. Configuration

Configuration precedence is CLI, environment, project TOML, user TOML, defaults.

```toml
[sec]
user_agent = "Required Name contact@example.com"
requests_per_second = 2.0
cache_ttl_hours = 24

[prices]
provider = "alpha-vantage"
api_key_env = "STOCKANALYZER_ALPHA_VANTAGE_KEY"
benchmark = "SPY"

[macro]
provider = "none"
api_key_env = "STOCKANALYZER_FRED_KEY"

[analysis]
years = 5
quarters = 8
max_peers = 5
materiality_percent_pretax_income = 5.0
materiality_percent_revenue = 1.0

[llm]
provider = "codex-cli"
model = ""
timeout_seconds = 900

[render]
formats = ["markdown", "html"]
currency_scale = "auto"
```

Secrets shall be read from environment variables or an operating-system secret store, never written to run manifests, logs, prompts, or reports.

## 18. Architecture

```text
CLI
 ├── configuration
 ├── run coordinator / state machine
 ├── provider adapters
 │    ├── SEC
 │    ├── Alpha Vantage / CSV
 │    └── FRED
 ├── immutable cache and provenance store
 ├── filing and XBRL parsers
 ├── normalization and concept registry
 ├── calculation engine
 ├── validation engine
 ├── research package builder
 ├── single-run LLM adapter
 └── schema validator and renderer
```

Recommended package layout:

```text
src/stockanalyzer/
  cli.py
  config.py
  runs.py
  models.py
  provenance.py
  providers/
  filings/
  xbrl/
  normalization/
  calculations/
  validation/
  research_package/
  llm/
  render/
  resources/
```

Business logic shall be importable and independent of CLI argument parsing. Network and LLM execution shall be injected behind interfaces for offline tests.

## 19. Technology Choices

### 19.1 Runtime

- Python 3.12 or newer;
- `httpx` for HTTP;
- `lxml` and `beautifulsoup4` for filing parsing;
- `pandas` or `polars` plus `pyarrow` for analytical tables;
- standard-library `decimal` for financial calculations requiring controlled precision;
- `pydantic` only if approved during implementation, otherwise dataclasses plus JSON Schema validation;
- `jinja2` for deterministic reports;
- `plotly` or `matplotlib` for deterministic charts;
- `weasyprint` as an optional PDF extra;
- `openpyxl` as an optional XLSX extra;
- `pytest`, `respx`, and `ruff` for verification.

Dependency selection is finalized during implementation. The core shall not require a database, web server, browser automation, or cloud service.

### 19.2 Storage

V1 uses the filesystem with content-addressed raw artifacts, JSON metadata, and Parquet analytical tables. SQLite is not required. Atomic writes use a temporary sibling file followed by rename.

## 20. Reliability, Security, and Legal Boundaries

- Treat filings and provider responses as untrusted input.
- Do not execute filing scripts, macros, attachments, or embedded content.
- Enforce response size, redirect, decompression, parser-depth, and timeout limits.
- Sanitize file names and prevent path traversal.
- Escape all narrative and source text during HTML rendering.
- Block external active content in generated HTML.
- Record dependency and application versions for reproducibility.
- Redact keys, email addresses outside the required SEC request header, and command credentials from logs.
- Display source/provider attribution and terms links where required.
- Include a disclaimer that output is informational research, may contain errors, and is not investment advice.
- Do not claim that SEC filing availability means endorsement or validation by the SEC.
- Do not redistribute third-party FRED series without checking the series notes and rights.

## 21. Performance and Operational Requirements

On a warm cache for a normal five-year/eight-quarter company:

- deterministic preparation should complete within 30 seconds on a contemporary laptop, excluding rendering;
- peak memory target is below 1 GB for a single run;
- the application makes zero network requests in `--offline` mode;
- rerendering makes zero data-provider or LLM calls;
- repeated collection does not redownload immutable accession artifacts whose hashes are known;
- logs are structured JSON Lines with stage, event, run ID, timestamp, duration, and error fields;
- console progress never mixes with machine-readable stdout when `--json` is selected.

Cold-run time depends on SEC response time, filing size, free-provider limits, and the configured LLM.

## 22. Testing Strategy

### 22.1 Unit tests

- ticker/CIK normalization;
- filing selection at point in time;
- XBRL context and dimension handling;
- fiscal period and derived-quarter logic;
- concept precedence and extension mapping;
- sign normalization;
- every financial formula and null rule;
- exceptional-item candidate classification;
- price alignment and return calculations;
- peer selection;
- citation construction;
- package budgeting;
- LLM response schema and numeric consistency validation.

### 22.2 Contract tests

Captured provider fixtures shall test SEC, Alpha Vantage, FRED, and imported CSV adapters without network access. Fixtures retain headers and representative success, limit, malformed, amendment, restatement, custom-tag, dimensional, and missing-data cases.

### 22.3 Golden-company integration tests

Use multiple frozen issuers representing:

- conventional industrial company;
- software company with material stock compensation;
- retailer with a non-calendar fiscal year;
- acquisitive company with restructuring and impairment;
- company with restated filings;
- company with negative earnings;
- issuer with material segment dimensions.

Expected normalized tables, calculations, validation findings, package hashes, and rendered sections are versioned fixtures. Tests never call a live LLM.

### 22.4 LLM adapter tests

A fake process emits valid, invalid, hallucinated-citation, numeric-conflict, timeout, and nonzero-exit responses. One integration test may use a manually authorized subscription CLI and is excluded from the default test suite.

### 22.5 Live smoke tests

Opt-in tests verify current provider compatibility while respecting rate limits. They do not assert mutable financial values; they assert response shape, identity, cache creation, and provenance.

## 23. Acceptance Criteria

V1 is accepted when all of the following hold:

1. A user can analyze a supported ticker with a declared SEC user agent and a free Alpha Vantage key.
2. The run preserves selected annual and quarterly reports, raw structured responses, and a complete source manifest.
3. The report contains at least five annual periods and eight quarters when the issuer provides sufficient history.
4. Earnings, cash flow, balance-sheet, per-share, valuation, and performance tables trace every value to source facts or formulas.
5. Exceptional items appear with category, amounts when evidenced, cash/noncash status when evidenced, recurrence context, and citations.
6. Sector/industry and peer classifications distinguish SEC facts from local mappings.
7. No post-`as_of` filing or price enters the run.
8. Validation blocks synthesis for ambiguous identity, invalid period construction, broken lineage, or manifest mutation.
9. A normal run invokes the LLM exactly once, and collection/rendering invoke it zero times.
10. An invalid LLM response is retained but not rendered as a successful stock sheet.
11. Markdown and HTML reports are professional, print-safe, accessible, and numerically identical.
12. A warm-cache offline rerun reproduces deterministic artifacts byte-for-byte, excluding explicitly volatile runtime metadata.
13. The default automated test suite makes no live network calls and incurs no provider or LLM charges.

## 24. Delivery Plan

### Increment 1: Deterministic SEC foundation

- CLI, configuration, run states, cache, provenance;
- ticker/CIK resolution, submissions, filing acquisition;
- Company Facts ingestion and raw source index;
- initial annual/quarterly normalized tables.

### Increment 2: Financial normalization

- filing-native XBRL verification;
- period engine, canonical registry, statement reconciliation;
- earnings, balance sheet, and cash-flow calculations;
- exceptional-item candidate records.

### Increment 3: Market and comparative context

- Alpha Vantage and CSV price adapters;
- return, valuation, benchmark, sector mapping, and peer logic;
- optional FRED adapter.

### Increment 4: Research package and one-run synthesis

- bounded package and citation catalog;
- subscription/local CLI adapter;
- response schema and rejection rules;
- complete evidence logging.

### Increment 5: Professional output

- Markdown and HTML templates;
- deterministic charts and source index;
- optional PDF/XLSX extras;
- golden-company acceptance suite and documentation.

## 25. Deferred Capabilities

- foreign issuer and IFRS normalization;
- bank, insurer, fund, REIT, and BDC-specific metric packs;
- licensed consensus estimates and earnings calendars;
- transcript and news ingestion;
- holdings and multi-company batch analysis;
- web interface;
- scheduled refresh and change reports;
- valuation models requiring explicit analyst assumptions, including DCF and scenario analysis;
- commercial classification systems such as GICS;
- real-time exchange data.

## 26. Material Risks and Mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Issuer-specific XBRL extensions | Missing or misclassified metrics | Filing-native relationships, mapping confidence, null instead of guess, golden fixtures |
| Amendments and restatements | Historical values change | Point-in-time selector, accession lineage, restatement flags |
| Free price-provider limits change | Runs lose valuation/returns | Provider interface, permanent cache, CSV import, graceful partial report |
| SIC is coarse or stale | Weak sector/peer comparisons | Label accurately, versioned mapping, explicit overrides, show selection trace |
| Exceptional items require judgment | Misleading normalized earnings | Separate candidate detection from interpretation; require sourced adjustment sets |
| Filing prose exceeds model context | Important evidence omitted | Deterministic section extraction, budget priority, visible truncation record |
| LLM changes or hallucinates | Unsupported narrative | One bounded run, schema, citations, numeric checks, fail closed |
| Free public sources lack consensus data | Market expectations absent | State limitation; do not substitute invented estimates |
| Provider terms change | Operational or redistribution risk | Record terms URLs, isolate adapters, check terms before release |

## 27. Authoritative External References

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — submissions and XBRL Company Facts endpoints, bulk archives, update behavior, and CORS limitation.
- [SEC Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) — indexes, archive layout, CIK behavior, and ticker/exchange association files.
- [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions) — declared automated user agent and current maximum request rate of 10 requests per second.
- [Alpha Vantage Support](https://www.alphavantage.co/support/) — current free allowance of up to 25 requests per day and real-time market-data limitation.
- [FRED API Overview](https://fred.stlouisfed.org/docs/api/fred/overview.html) — REST API capabilities.
- [FRED API Keys](https://fred.stlouisfed.org/docs/api/fred/v2/api_key.html) — API-key requirement.
- [FRED API Terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html) — third-party series rights and application obligations.

These references describe external services as of the specification date. Implementation shall verify provider documentation and terms before release and shall not hardcode free-tier allowances as permanent guarantees.

## 28. Definition of Done

The project is done when the acceptance criteria pass against frozen representative issuers, the full non-networked test suite passes, a live free-tier smoke test completes without prohibited access or paid data, and a reviewer can trace every material number and factual narrative claim in the final stock sheet to the frozen evidence package.

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TabStopType, TabStopPosition, ExternalHyperlink
} = require('/sessions/wonderful-dreamy-cori/patent_work/node_modules/docx');
const fs = require('fs');

// ─── Helpers ───────────────────────────────────────────────────────────────

const pt = (n) => n * 2; // half-points

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 120 },
    children: [new TextRun({ text, bold: true, size: pt(14), font: 'Arial' })]
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, size: pt(12), font: 'Arial' })]
  });
}

function h3(text) {
  return new Paragraph({
    spacing: { before: 180, after: 60 },
    children: [new TextRun({ text, bold: true, underline: {}, size: pt(12), font: 'Arial' })]
  });
}

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 0, after: 160 },
    indent: opts.indent ? { left: 720 } : undefined,
    alignment: opts.justify ? AlignmentType.BOTH : AlignmentType.LEFT,
    children: [new TextRun({ text, size: pt(12), font: 'Arial' })]
  });
}

function pJust(text) { return p(text, { justify: true }); }

function claimPara(text, level = 0) {
  return new Paragraph({
    spacing: { before: 80, after: 80 },
    indent: { left: level === 0 ? 0 : 720, hanging: level === 0 ? 0 : 360 },
    children: [new TextRun({ text, size: pt(12), font: 'Arial' })]
  });
}

function blankLine() {
  return new Paragraph({ spacing: { before: 0, after: 0 }, children: [new TextRun('')] });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function centeredBold(text, size = 14) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, bold: true, size: pt(size), font: 'Arial' })]
  });
}

function labeledLine(label, value) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    children: [
      new TextRun({ text: label + ': ', bold: true, size: pt(12), font: 'Arial' }),
      new TextRun({ text: value, size: pt(12), font: 'Arial' })
    ]
  });
}

// ─── Border helpers for tables ──────────────────────────────────────────────

function cellBorder(color = 'BBBBBB') {
  const b = { style: BorderStyle.SINGLE, size: 1, color };
  return { top: b, bottom: b, left: b, right: b };
}

function headerCell(text, widthDxa) {
  return new TableCell({
    width: { size: widthDxa, type: WidthType.DXA },
    borders: cellBorder('444444'),
    shading: { fill: 'D0D8E4', type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({ text, bold: true, size: pt(11), font: 'Arial' })]
    })]
  });
}

function dataCell(text, widthDxa) {
  return new TableCell({
    width: { size: widthDxa, type: WidthType.DXA },
    borders: cellBorder(),
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({ text, size: pt(11), font: 'Arial' })]
    })]
  });
}

// ─── CLAIMS SECTION ─────────────────────────────────────────────────────────

const claims = [
  // ── CLAIM 1 (Independent Method – Bi-Level Causal DAG) ──────────────────
  claimPara('1. A computer-implemented method for autonomous root cause attribution in a fifth-generation (5G) telecommunications network, comprising:'),
  claimPara('(a) receiving, by a multi-source telemetry ingestion engine (MTIE), a plurality of telemetry streams from a set of network functions (NFs) operating within the 5G network, wherein the telemetry streams comprise at least: (i) container-level state signals reflecting the operational lifecycle of each NF process, (ii) key performance indicators (KPIs) sampled at a sub-second cadence from each NF, and (iii) inter-NF communication signals capturing signalling exchange volumes and latencies;', 1),
  claimPara('(b) constructing, by a causal inference engine (CIE), a first-level directed acyclic graph (DAG) in which each node represents an NF and each directed edge represents a statistically established causal relationship derived from Granger causality analysis of the telemetry streams received in step (a);', 1),
  claimPara('(c) pruning the first-level DAG by a dynamic causal graph manager (DCGM) to remove spurious edges that do not meet a configurable statistical significance threshold, thereby retaining only causal edges with established directional temporal precedence;', 1),
  claimPara('(d) computing, by a root cause scoring module (RCSM) for each NF node in the pruned first-level DAG, a composite root cause score that integrates: (i) a Granger temporal precedence weight reflecting the degree to which that NF\'s metrics temporally precede degradation in downstream NFs, (ii) a topology centrality measure quantifying the NF\'s structural position within the causal graph, and (iii) an infrastructure state signal derived from the container-level state of the NF process;', 1),
  claimPara('(e) identifying a candidate root cause NF as the NF with the highest composite root cause score computed in step (d);', 1),
  claimPara('(f) constructing, by a slice ensemble attributor, a plurality of second-level slice sub-DAGs, wherein each slice sub-DAG represents inferred causal relationships among NFs within a respective network slice of the 5G network;', 1),
  claimPara('(g) computing, for the candidate root cause NF identified in step (e), across the plurality of second-level slice sub-DAGs: (i) a slice breadth metric defined as the fraction of registered network slices in which the candidate root cause NF exhibits a non-zero causal path weight; and (ii) an isolation type classification that categorizes the fault as slice-isolated when the slice breadth is strictly less than 1.0, or as infrastructure-wide when the slice breadth equals 1.0;', 1),
  claimPara('(h) generating a bi-level ensemble attribution report that fuses the composite root cause score from step (d) with the slice breadth metric and isolation type from step (g), wherein the bi-level ensemble attribution report provides fault isolation granularity that neither the first-level DAG alone nor any individual second-level slice sub-DAG alone can provide.', 1),
  blankLine(),

  // ── CLAIM 2 (Dependent on 1 – Granger analysis detail) ──────────────────
  claimPara('2. The method of claim 1, wherein the Granger causality analysis of step (b) comprises:'),
  claimPara('(i) applying a vector autoregression (VAR) model to time-aligned telemetry windows of configurable length for each pair of NFs in the network;', 1),
  claimPara('(ii) computing an F-statistic for each NF pair to test the null hypothesis that past values of a first NF do not improve prediction of a second NF beyond the second NF\'s own history; and', 1),
  claimPara('(iii) directing a causal edge from the first NF to the second NF if the F-statistic exceeds a configurable p-value threshold, establishing the first NF as a Granger cause of the second NF.', 1),
  blankLine(),

  // ── CLAIM 3 (Dependent on 1 – Multi-source telemetry domains) ──────────
  claimPara('3. The method of claim 1, wherein the telemetry streams of step (a) are organized into four hierarchical telemetry domains: (i) an infrastructure domain comprising container process state and resource utilization signals; (ii) a control-plane domain comprising NF registration, heartbeat, and session management KPIs; (iii) a user-plane domain comprising data-path throughput, latency, and packet loss KPIs; and (iv) a slice domain comprising per-slice QoS enforcement signals and slice admission control counters.'),
  blankLine(),

  // ── CLAIM 4 (Dependent on 1 – DCGM recalibration) ──────────────────────
  claimPara('4. The method of claim 1, further comprising:'),
  claimPara('(i) after generating the bi-level ensemble attribution report of step (h), executing a remediation action selected by a confidence-gated remediation action engine (RAE), wherein the RAE selects the remediation action only when the composite root cause score of the candidate root cause NF exceeds a configurable confidence threshold; and', 1),
  claimPara('(ii) after the remediation action is executed, observing outcome telemetry and updating the first-level DAG by recalibrating the edge weights of the dynamic causal graph manager based on whether the executed remediation action produced an observed improvement in the KPIs of the candidate root cause NF and its downstream NFs.', 1),
  blankLine(),

  // ── CLAIM 5 (Dependent on 4 – action taxonomy) ──────────────────────────
  claimPara('5. The method of claim 4, wherein the remediation action selected by the confidence-gated RAE is drawn from a predefined action taxonomy comprising at least: (i) restart_pod, which triggers a container restart of the candidate root cause NF; (ii) rollback_config, which reverts the most recent configuration change applied to the candidate root cause NF; and (iii) scale_out, which provisions one or more additional instances of the candidate root cause NF; and wherein the RAE selects among these actions based on the isolation type classification produced in step (g) of claim 1.'),
  blankLine(),

  // ── CLAIM 6 (Dependent on 1 – pcf_timeout slice-isolation proof) ────────
  claimPara('6. The method of claim 1, wherein the bi-level ensemble attribution report of step (h) uniquely discriminates a slice-isolated NF fault from an infrastructure-wide NF fault of the same NF type by virtue of the slice breadth metric of step (g), such that a first fault scenario in which the candidate root cause NF is absent from a strict subset of registered slices produces a slice breadth strictly less than 1.0 and an isolation type of slice-isolated, whereas a second fault scenario in which the same NF type fails in a manner that affects all registered slices produces a slice breadth of 1.0 and an isolation type of infrastructure-wide, and wherein the composite root cause score of step (d) alone is insufficient to distinguish the first fault scenario from the second fault scenario.'),
  blankLine(),

  // ── CLAIM 7 (Independent System Claim) ──────────────────────────────────
  claimPara('7. A system for autonomous root cause attribution in a fifth-generation (5G) telecommunications network, comprising:'),
  claimPara('a multi-source telemetry ingestion engine (MTIE) configured to continuously receive and normalize telemetry streams from a plurality of network functions (NFs) in the 5G network, wherein the telemetry streams comprise container-level state signals, key performance indicators, and inter-NF communication signals;', 1),
  claimPara('a causal inference engine (CIE) operably coupled to the MTIE and configured to construct a first-level directed acyclic graph (DAG) in which directed edges represent statistically established Granger-causal relationships derived from the normalized telemetry streams;', 1),
  claimPara('a dynamic causal graph manager (DCGM) operably coupled to the CIE and configured to: (i) prune statistically insignificant edges from the first-level DAG; and (ii) recalibrate edge weights in the first-level DAG based on observed remediation outcome telemetry;', 1),
  claimPara('a root cause scoring module (RCSM) operably coupled to the DCGM and configured to compute, for each NF in the pruned first-level DAG, a composite root cause score integrating Granger temporal precedence weight, topology centrality measure, and infrastructure state signal;', 1),
  claimPara('a slice ensemble attributor operably coupled to the RCSM and configured to construct a plurality of second-level slice sub-DAGs and compute, for a candidate root cause NF identified by the RCSM, a slice breadth metric and an isolation type classification; and', 1),
  claimPara('a fault report generator (FRG) configured to produce a bi-level ensemble attribution report fusing the composite root cause score from the RCSM with the slice breadth metric and isolation type from the slice ensemble attributor.', 1),
  blankLine(),

  // ── CLAIM 8 (Dependent on 7 – RAE subsystem) ────────────────────────────
  claimPara('8. The system of claim 7, further comprising a confidence-gated remediation action engine (RAE) operably coupled to the fault report generator and configured to: (i) select a remediation action from a predefined taxonomy when the composite root cause score in the bi-level ensemble attribution report exceeds a configurable confidence threshold; (ii) execute the selected remediation action against the 5G network; and (iii) supply resulting outcome telemetry to the dynamic causal graph manager for recalibration of the first-level DAG.'),
  blankLine(),

  // ── CLAIM 9 (Dependent on 7 – real-time API) ────────────────────────────
  claimPara('9. The system of claim 7, wherein the fault report generator (FRG) exposes a REST API endpoint that: (i) accepts fault injection commands specifying a target NF and fault type; (ii) returns a bi-level ensemble attribution report in a structured JSON payload comprising at minimum the candidate root cause NF identifier, composite root cause score, slice breadth metric, and isolation type classification; and (iii) streams health and pipeline status at a configurable polling interval.'),
  blankLine(),

  // ── CLAIM 10 (Dependent on 7 – buffer and cycle architecture) ───────────
  claimPara('10. The system of claim 7, wherein the multi-source telemetry ingestion engine (MTIE) comprises a ring buffer of configurable capacity that stores a rolling window of normalized telemetry samples, and wherein the causal inference engine (CIE) operates in cycles of configurable duration over the ring buffer contents, such that the first-level DAG is updated each cycle without requiring a full historical replay of telemetry data.'),
  blankLine(),

  // ── CLAIM 11 (Independent – Computer-Readable Medium) ───────────────────
  claimPara('11. A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, cause the processors to perform operations comprising:'),
  claimPara('ingesting multi-source telemetry from a plurality of network functions (NFs) in a fifth-generation (5G) network, the telemetry comprising container-level state signals, key performance indicators, and inter-NF communication signals;', 1),
  claimPara('constructing a first-level directed acyclic graph (DAG) of causal relationships among the NFs using Granger causality analysis of the telemetry;', 1),
  claimPara('scoring each NF in the first-level DAG with a composite root cause score that integrates Granger temporal precedence, topology centrality, and infrastructure state;', 1),
  claimPara('identifying a candidate root cause NF based on the composite root cause scores;', 1),
  claimPara('constructing a plurality of second-level slice sub-DAGs, one per network slice, and computing for the candidate root cause NF a slice breadth metric and an isolation type classification; and', 1),
  claimPara('generating a bi-level ensemble attribution report fusing the composite root cause score with the slice breadth metric and isolation type classification.', 1),
  blankLine(),

  // ── CLAIM 12 (Dependent on 11 – recalibration) ──────────────────────────
  claimPara('12. The non-transitory computer-readable medium of claim 11, wherein the operations further comprise: executing a confidence-gated remediation action based on the bi-level ensemble attribution report; observing post-remediation outcome telemetry; and updating the first-level DAG by recalibrating Granger edge weights based on the observed outcome telemetry.'),
  blankLine(),

  // ── CLAIM 13 (Dependent on 1 – confidence gate) ─────────────────────────
  claimPara('13. The method of claim 1, wherein the composite root cause score of step (d) is computed as a product of: (i) a confidence factor derived from the normalized magnitude of the Granger F-statistic for the highest-scoring causal path terminating at the candidate root cause NF; (ii) a severity multiplier derived from the observed magnitude of KPI degradation; and (iii) an infrastructure boost factor that takes a value greater than 1.0 when the container-level state signal of the candidate root cause NF indicates an abnormal lifecycle state, and 1.0 otherwise.'),
  blankLine(),

  // ── CLAIM 14 (Dependent on 1 – continuous pipeline) ─────────────────────
  claimPara('14. The method of claim 1, wherein steps (a) through (h) execute in a continuous pipeline loop at a configurable cycle interval, such that the first-level DAG and the bi-level ensemble attribution report are updated without human intervention across successive fault events, and wherein the pipeline maintains a fill percentage metric tracking the proportion of the telemetry buffer that has been populated with valid observations.'),
  blankLine(),

  // ── CLAIM 15 (Dependent on 6 – disambiguation table) ────────────────────
  claimPara('15. The method of claim 6, wherein the bi-level ensemble attribution report further comprises a per-slice attribution table enumerating, for each registered network slice: (i) the causal path weight of the candidate root cause NF within that slice\'s sub-DAG; (ii) a binary indicator of whether the candidate root cause NF is present in that slice; and (iii) the resulting contribution of that slice to the slice breadth metric.'),
];

// ─── SPECIFICATION TEXT ────────────────────────────────────────────────────

const specChildren = [

  // ── COVER ────────────────────────────────────────────────────────────────
  blankLine(), blankLine(),
  centeredBold('UNITED STATES PATENT APPLICATION', 14),
  blankLine(),
  centeredBold('NON-PROVISIONAL APPLICATION', 12),
  blankLine(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Under 35 U.S.C. §§ 111(a), 119, 120', size: pt(11), font: 'Arial', italics: true })]
  }),
  blankLine(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    border: { top: { style: BorderStyle.SINGLE, size: 4, color: '000000' } },
    spacing: { before: 240, after: 0 },
    children: [new TextRun('')]
  }),
  blankLine(),

  labeledLine('Title', 'SYSTEM AND METHOD FOR SLICE-TOPOLOGY-AWARE CAUSAL ROOT CAUSE ANALYSIS AND CLOSED-LOOP REMEDIATION FOR CLOUD-NATIVE 5G STANDALONE CORE NETWORKS'),
  blankLine(),
  labeledLine('Inventor(s)', 'Krishna Kumar Gattupalli'),
  labeledLine('Applicant', 'Krishna Kumar Gattupalli'),
  labeledLine('Address', '6230 Lake Brook DR, Celina, Texas 75009, US'),
  labeledLine('Filing Basis', 'Non-provisional under 35 U.S.C. § 111(a), claiming priority to Provisional Application No. 64/015,070'),
  labeledLine('Provisional App #', '64/015,070 — "System and Method for Slice-Topology-Aware Causal Root Cause Analysis and Closed-Loop Remediation for Cloud-Native 5G Standalone Core Networks" — Status: Undergoing Preexam Processing'),
  labeledLine('Priority Date', '[INSERT OFFICIAL USPTO FILING DATE FROM PROVISIONAL — this date starts the 12-month Paris Convention clock for foreign filing]'),
  labeledLine('Non-Provisional Deadline', 'One (1) year from provisional filing date under 35 U.S.C. § 119(e)'),
  labeledLine('PCT Deadline', '12 months from provisional filing date under Paris Convention Art. 4'),
  labeledLine('Correspondence Address', '[Attorney/Agent address to be inserted]'),
  blankLine(), blankLine(),

  pageBreak(),

  // ── TITLE ────────────────────────────────────────────────────────────────
  h1('TITLE OF THE INVENTION'),
  p('SYSTEM AND METHOD FOR SLICE-TOPOLOGY-AWARE CAUSAL ROOT CAUSE ANALYSIS AND CLOSED-LOOP REMEDIATION FOR CLOUD-NATIVE 5G STANDALONE CORE NETWORKS'),
  blankLine(),

  // ── CROSS REFERENCE ─────────────────────────────────────────────────────
  h1('CROSS-REFERENCE TO RELATED APPLICATIONS'),
  pJust('This application claims priority to and the benefit of U.S. Provisional Patent Application No. 64/015,070, filed [INSERT OFFICIAL FILING DATE — see USPTO Patent Center application record], entitled "System and Method for Slice-Topology-Aware Causal Root Cause Analysis and Closed-Loop Remediation for Cloud-Native 5G Standalone Core Networks," the entire contents of which are incorporated herein by reference.'),
  blankLine(),

  // ── FIELD ────────────────────────────────────────────────────────────────
  h1('FIELD OF THE INVENTION'),
  pJust('The present invention relates to autonomous fault management in fifth-generation (5G) telecommunications networks and, more particularly, to computer-implemented methods and systems that employ bi-level causal directed acyclic graphs (DAGs), multi-source telemetry analysis, and confidence-gated remediation actions to identify root causes of network function failures with slice-level isolation granularity.'),
  blankLine(),

  // ── BACKGROUND ──────────────────────────────────────────────────────────
  h1('BACKGROUND OF THE INVENTION'),
  pJust('Fifth-generation (5G) telecommunications networks are characterized by a highly disaggregated, software-defined architecture in which network functions (NFs) — such as the Access and Mobility Management Function (AMF), Session Management Function (SMF), Policy Control Function (PCF), User Data Management Function (UDM), and NF Repository Function (NRF) — are deployed as containerized microservices interconnected through service-based interfaces.'),
  blankLine(),
  pJust('This architectural disaggregation dramatically increases operational complexity. A single physical failure or misconfiguration in one NF can propagate causally through service-based interfaces to degrade multiple downstream NFs simultaneously, producing an alarm storm in which six or more correlated fault indicators fire concurrently, each appearing as a plausible root cause to conventional threshold-based or rule-based monitoring systems.'),
  blankLine(),
  pJust('Network slicing further compounds this complexity. A 5G network may simultaneously host multiple logical network slices — such as an enhanced Mobile Broadband (eMBB) slice, a massive Internet of Things (mIoT) slice, and an Ultra-Reliable Low-Latency Communications (URLLC) slice — each of which consumes shared NF resources. The same NF failure can, depending on the topology of slice-to-NF bindings, manifest as a slice-isolated fault (affecting only a subset of slices) or as an infrastructure-wide fault (affecting all slices). Conventional root cause analysis (RCA) systems that operate solely at the NF layer cannot distinguish these two cases, leading to incorrect remediation selection: an infrastructure-wide restart_pod action applied to a slice-isolated PCF timeout wastes resources and may disrupt unaffected slices.'),
  blankLine(),
  pJust('Prior art approaches to automated RCA in 5G networks suffer from several well-documented deficiencies:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'priorbullets', level: 0 },
    children: [new TextRun({ text: 'Rule-based expert systems require manual authoring of fault signatures and cannot generalize to novel fault combinations not anticipated during system design.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'priorbullets', level: 0 },
    children: [new TextRun({ text: 'Correlation-based anomaly detection systems identify statistical co-occurrence of alarms but cannot determine causal direction: they cannot distinguish whether NF-A caused NF-B to fail, or vice versa.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'priorbullets', level: 0 },
    children: [new TextRun({ text: 'Single-layer causal graph systems operate exclusively at the NF layer and produce identical root-cause scores for faults that differ only in their slice-level impact, making it impossible to select the correct remediation action.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'priorbullets', level: 0 },
    children: [new TextRun({ text: 'Machine-learning classifiers trained on labeled fault datasets suffer from distribution shift when network topology or traffic patterns evolve, and require significant labeled training data that is expensive to obtain in production environments.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  pJust('There exists a need in the art for an autonomous RCA system that: (a) establishes causal direction — not mere correlation — among NF faults using formal statistical causal inference; (b) operates at two levels of granularity (NF-layer and slice-layer) to produce fault isolation that neither level alone can achieve; (c) continuously recalibrates its causal model based on the outcomes of executed remediation actions; and (d) requires no labeled training data or manually authored fault signatures.'),
  blankLine(),

  // ── SUMMARY ─────────────────────────────────────────────────────────────
  h1('SUMMARY OF THE INVENTION'),
  pJust('The present invention provides a computer-implemented method and system for autonomous root cause attribution in a 5G telecommunications network, using a bi-level causal directed acyclic graph (DAG) architecture comprising a first-level NF-layer DAG and a plurality of second-level slice sub-DAGs.'),
  blankLine(),
  pJust('In a first aspect, the invention provides a computer-implemented method comprising: receiving multi-source telemetry from a plurality of 5G NFs; constructing a first-level causal DAG using Granger causality analysis; computing composite root cause scores for each NF integrating temporal precedence, topology centrality, and infrastructure state signals; identifying a candidate root cause NF; constructing second-level slice sub-DAGs; computing a slice breadth metric and isolation type for the candidate root cause NF; and generating a bi-level ensemble attribution report fusing first-level and second-level evidence.'),
  blankLine(),
  pJust('In a second aspect, the invention provides a system comprising a Multi-source Telemetry Ingestion Engine (MTIE), a Causal Inference Engine (CIE), a Dynamic Causal Graph Manager (DCGM), a Root Cause Scoring Module (RCSM), a Slice Ensemble Attributor, a Fault Report Generator (FRG), and a confidence-gated Remediation Action Engine (RAE) that recalibrates the causal graph based on remediation outcomes.'),
  blankLine(),
  pJust('In a third aspect, the invention provides a non-transitory computer-readable medium storing instructions for performing the bi-level causal attribution method.'),
  blankLine(),
  pJust('The bi-level approach of the present invention uniquely enables discrimination of slice-isolated faults from infrastructure-wide faults of the same NF type. In the canonical proof-of-concept embodiment described herein, a PCF timeout fault produces a slice breadth of 0.667 (PCF absent from one of three slices) and an isolation type of "slice-isolated," whereas an NRF crash produces a slice breadth of 1.0 and an isolation type of "infrastructure-wide," despite both faults producing indistinguishable composite root cause scores at the first level alone.'),
  blankLine(),

  // ── DRAWINGS ─────────────────────────────────────────────────────────────
  h1('BRIEF DESCRIPTION OF THE DRAWINGS'),
  p('FIG. 1 is a block diagram illustrating the overall system architecture of the autonomous root cause attribution system according to an embodiment of the invention, showing the MTIE, CIE, DCGM, RCSM, Slice Ensemble Attributor, FRG, and RAE modules and their interconnections.'),
  blankLine(),
  p('FIG. 2 is a diagram illustrating the bi-level causal DAG structure according to an embodiment of the invention, showing the first-level NF-layer DAG above a dashed boundary line and three second-level slice sub-DAGs (eMBB, mIoT, URLLC) below it, with reference numerals identifying each DAG node and directed causal edge.'),
  blankLine(),
  p('FIG. 3 is a flowchart illustrating the computer-implemented method for bi-level causal attribution according to an embodiment of the invention, showing steps (a) through (h) of Claim 1 in sequential order with a recalibration feedback loop from the RAE back to the DCGM.'),
  blankLine(),
  p('FIG. 4 is a diagram illustrating the recalibration loop according to an embodiment of the invention, showing how post-remediation outcome telemetry flows from the 5G network back to the DCGM to update first-level DAG edge weights after each executed remediation action.'),
  blankLine(),
  p('FIG. 5 is a table illustrating the canonical bi-level discrimination proof according to an embodiment of the invention, showing five fault scenarios, their first-level composite root cause scores, slice breadth metrics, and isolation type classifications, demonstrating that first-level scores alone are insufficient to distinguish pcf_timeout from nrf_crash.'),
  blankLine(),

  pageBreak(),

  // ── DETAILED DESCRIPTION ─────────────────────────────────────────────────
  h1('DETAILED DESCRIPTION OF THE PREFERRED EMBODIMENTS'),
  pJust('The following detailed description sets forth specific embodiments of the invention with sufficient particularity to enable one of ordinary skill in the art to make and use the invention without undue experimentation. Headings are provided for organizational convenience only and do not limit the scope of the invention.'),
  blankLine(),

  // 1. System Overview
  h2('1. System Overview'),
  pJust('Referring to FIG. 1, an embodiment of the autonomous root cause attribution system 100 for a 5G telecommunications network comprises the following principal modules operably interconnected:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Multi-source Telemetry Ingestion Engine (MTIE) 110 — continuously receives and normalizes telemetry streams from the 5G NF layer.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Causal Inference Engine (CIE) 120 — constructs first-level DAG from normalized telemetry using Granger causality analysis.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Dynamic Causal Graph Manager (DCGM) 130 — prunes and recalibrates the first-level DAG.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Root Cause Scoring Module (RCSM) 140 — computes composite root cause scores for each NF.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Slice Ensemble Attributor 150 — constructs second-level slice sub-DAGs and computes slice breadth and isolation type.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Fault Report Generator (FRG) 160 — assembles and exposes the bi-level ensemble attribution report via a REST API.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'modulelist', level: 0 },
    children: [new TextRun({ text: 'Remediation Action Engine (RAE) 170 — selects and executes remediation actions when the confidence gate is satisfied, and supplies outcome telemetry to the DCGM.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  pJust('In the preferred embodiment, modules 110–170 are implemented as Python software components deployed on a host system with access to the 5G network management plane. The FRG 160 exposes a REST API on a configurable port (default 8080). The pipeline operates in a continuous cycle loop at a configurable interval (default 30 seconds), updating the first-level DAG and bi-level attribution report without human intervention.'),
  blankLine(),

  // 2. Multi-Source Telemetry Ingestion (MTIE)
  h2('2. Multi-Source Telemetry Ingestion Engine (MTIE) 110'),
  pJust('The MTIE 110 receives telemetry from the 5G NF layer and organizes it into four hierarchical telemetry domains:'),
  blankLine(),
  pJust('Domain I — Infrastructure Domain: Container-level state signals reflecting the lifecycle of each NF process. In the preferred embodiment, container state is encoded as a numeric score derived from the operational state of the NF process (e.g., running, paused, exited, restarting). This domain provides a direct indicator of whether an NF process is functional, independently of its network-visible KPIs. The infrastructure state signal is incorporated as the infrastructure boost factor in the composite root cause score (see Section 4).'),
  blankLine(),
  pJust('Domain II — Control-Plane Domain: NF registration status, heartbeat signals, session management KPIs, and NF-to-NF signalling exchange volumes, sampled at a sub-second cadence.'),
  blankLine(),
  pJust('Domain III — User-Plane Domain: Data-path throughput, round-trip latency, and packet loss measurements per NF, sampled continuously.'),
  blankLine(),
  pJust('Domain IV — Slice Domain: Per-slice quality-of-service (QoS) enforcement signals and slice admission control counters, one entry per registered network slice (e.g., eMBB, mIoT, URLLC).'),
  blankLine(),
  pJust('The MTIE 110 stores normalized telemetry in a ring buffer of configurable capacity. The ring buffer maintains a fill-percentage metric (buffer_fill_pct) tracking the proportion of the buffer populated with valid observations. The CIE 120 reads from the ring buffer at each cycle and does not require a full historical replay of telemetry.'),
  blankLine(),

  // 3. Causal Inference Engine (CIE) and DCGM
  h2('3. Causal Inference Engine (CIE) 120 and Dynamic Causal Graph Manager (DCGM) 130'),
  h3('3.1 Granger Causality Analysis'),
  pJust('The CIE 120 constructs the first-level NF-layer DAG using Granger causality analysis. For each ordered pair of NFs (NF_i, NF_j) in the network, the CIE applies a Vector Autoregression (VAR) model to a time-aligned telemetry window of configurable length drawn from the ring buffer. The CIE computes an F-statistic testing the null hypothesis that past values of NF_i\'s KPI time series do not improve prediction of NF_j\'s KPI time series beyond NF_j\'s own history. If the F-statistic exceeds a configurable p-value threshold (default p < 0.05), a directed causal edge is added from NF_i to NF_j in the first-level DAG, establishing NF_i as a Granger cause of NF_j.'),
  blankLine(),
  pJust('This approach establishes causal direction — not mere statistical correlation — between NF pairs, enabling the system to determine that NF_i\'s degradation temporally precedes and predicts NF_j\'s degradation, rather than that both degraded simultaneously due to a third common cause.'),
  blankLine(),
  h3('3.2 DAG Pruning'),
  pJust('The DCGM 130 prunes the first-level DAG by removing edges that do not meet the configurable statistical significance threshold. Following pruning, the first-level DAG contains only causal edges with established directional temporal precedence.'),
  blankLine(),
  h3('3.3 Recalibration'),
  pJust('After each remediation action executed by the RAE 170, the DCGM 130 receives outcome telemetry and recalibrates the first-level DAG edge weights. If the remediation action targeting NF_i produced an observed improvement in NF_i\'s KPIs and downstream NF_j\'s KPIs, the DCGM reinforces the causal edge weight from NF_i to NF_j. If no improvement is observed, the edge weight is attenuated. This continuous recalibration enables the system to learn from experience without requiring labeled training data.'),
  blankLine(),

  // 4. Root Cause Scoring Module (RCSM)
  h2('4. Root Cause Scoring Module (RCSM) 140'),
  pJust('The RCSM 140 computes a composite root cause score S_i for each NF_i in the pruned first-level DAG. In the preferred embodiment, S_i is computed as:'),
  blankLine(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 80 },
    children: [new TextRun({ text: 'S_i = G_i × C_i × (1 + B_i)', size: pt(12), font: 'Courier New', bold: false })]
  }),
  blankLine(),
  pJust('where:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    indent: { left: 720 },
    children: [new TextRun({ text: 'G_i (Granger Temporal Precedence Weight) — the normalized magnitude of the Granger F-statistic for the highest-scoring causal path in the first-level DAG that terminates at NF_i as a downstream effect, quantifying the degree to which NF_i\'s metrics temporally precede degradation in other NFs.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    indent: { left: 720 },
    children: [new TextRun({ text: 'C_i (Topology Centrality Measure) — a graph-theoretic measure of NF_i\'s structural position within the causal graph, computed as the fraction of all causal paths in the first-level DAG that pass through NF_i (betweenness centrality). NFs that are causal ancestors of many other NFs receive higher centrality scores.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    indent: { left: 720 },
    children: [new TextRun({ text: 'B_i (Infrastructure Boost Factor) — a scalar greater than 0.0 when the container-level state signal of NF_i indicates an abnormal lifecycle state (e.g., paused, exited, restarting), and 0.0 otherwise. This factor amplifies the composite score for NFs whose infrastructure state is directly degraded, ensuring that container-observable failures are ranked above NFs that are merely downstream KPI victims.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  pJust('The NF with the highest composite root cause score S_i is identified as the candidate root cause NF. In the preferred embodiment, this NF is passed to the Slice Ensemble Attributor 150 for second-level analysis.'),
  blankLine(),

  // 5. Slice Ensemble Attributor
  h2('5. Slice Ensemble Attributor 150'),
  h3('5.1 Second-Level Slice Sub-DAG Construction'),
  pJust('The Slice Ensemble Attributor 150 maintains a registry of network slices active in the 5G network (e.g., eMBB, mIoT, URLLC). For each registered slice, the Attributor constructs a second-level slice sub-DAG representing the causal relationships among NFs within that slice. A causal edge from NF_i to NF_j appears in a slice\'s sub-DAG only if both NF_i and NF_j are bound to that slice and a causal edge from NF_i to NF_j exists in the first-level DAG.'),
  blankLine(),
  h3('5.2 Slice Breadth Metric and Isolation Type'),
  pJust('For the candidate root cause NF (NF_rc) identified by the RCSM 140, the Slice Ensemble Attributor 150 computes the following across all registered slice sub-DAGs:'),
  blankLine(),
  pJust('Slice Breadth (SB): the fraction of registered network slices in which NF_rc exhibits a non-zero causal path weight in the slice\'s sub-DAG. Formally:'),
  blankLine(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 80 },
    children: [new TextRun({ text: 'SB = |{slice s : path_weight(NF_rc, s) > 0}| / |{all registered slices}|', size: pt(12), font: 'Courier New' })]
  }),
  blankLine(),
  pJust('Isolation Type: a categorical classification of the fault based on the slice breadth:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    indent: { left: 720 },
    children: [new TextRun({ text: '"slice-isolated" — when SB < 1.0, indicating that NF_rc is absent from at least one registered slice, and the fault\'s impact is therefore contained within a subset of slices.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    indent: { left: 720 },
    children: [new TextRun({ text: '"infrastructure-wide" — when SB = 1.0, indicating that NF_rc affects all registered slices.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  h3('5.3 Canonical Discrimination Proof'),
  pJust('In the canonical embodiment demonstrated during reduction to practice, five fault scenarios were injected into a running 5G network: nrf_crash, amf_crash, smf_crash, pcf_timeout, and udm_crash. All five scenarios produced identical composite root cause score gaps at the first level (gap = 0.01), making them indistinguishable by the RCSM 140 alone. The Slice Ensemble Attributor 150 discriminated pcf_timeout from the remaining four scenarios:'),
  blankLine(),

  // Table: Canonical discrimination proof
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1800, 1500, 1560, 1500, 2000, 1000],
    rows: [
      new TableRow({
        tableHeader: true,
        children: [
          headerCell('Scenario', 1800),
          headerCell('Expected NF', 1500),
          headerCell('L1 Score Gap', 1560),
          headerCell('Slice Breadth', 1500),
          headerCell('Isolation Type', 2000),
          headerCell('Match', 1000),
        ]
      }),
      new TableRow({ children: [dataCell('nrf_crash', 1800), dataCell('nrf', 1500), dataCell('0.01 (identical)', 1560), dataCell('1.000', 1500), dataCell('infrastructure-wide', 2000), dataCell('HIT', 1000)] }),
      new TableRow({ children: [dataCell('amf_crash', 1800), dataCell('amf', 1500), dataCell('0.01 (identical)', 1560), dataCell('1.000', 1500), dataCell('infrastructure-wide', 2000), dataCell('HIT', 1000)] }),
      new TableRow({ children: [dataCell('smf_crash', 1800), dataCell('smf', 1500), dataCell('0.01 (identical)', 1560), dataCell('1.000', 1500), dataCell('infrastructure-wide', 2000), dataCell('HIT', 1000)] }),
      new TableRow({ children: [dataCell('pcf_timeout', 1800), dataCell('pcf', 1500), dataCell('0.01 (identical)', 1560), dataCell('0.667 (*)', 1500), dataCell('slice-isolated (*)', 2000), dataCell('HIT', 1000)] }),
      new TableRow({ children: [dataCell('udm_crash', 1800), dataCell('udm', 1500), dataCell('0.01 (identical)', 1560), dataCell('1.000', 1500), dataCell('infrastructure-wide', 2000), dataCell('HIT', 1000)] }),
    ]
  }),
  new Paragraph({
    spacing: { before: 60, after: 120 },
    children: [new TextRun({ text: '(*) PCF is absent from the mIoT slice (path_weight = 0, nf_present = False), yielding SB = 2/3 = 0.667.', size: pt(10), font: 'Arial', italics: true })]
  }),
  blankLine(),
  pJust('The above table demonstrates the core inventive contribution: the first-level DAG scores are identical for all five scenarios, and the second-level slice sub-DAGs are required to disambiguate pcf_timeout from the remaining four. This bi-level discrimination is the enabling capability for correct remediation action selection (rollback_config for pcf_timeout versus restart_pod for infrastructure-wide faults).'),
  blankLine(),

  // 6. Fault Report Generator
  h2('6. Fault Report Generator (FRG) 160'),
  pJust('The FRG 160 assembles the bi-level ensemble attribution report from the outputs of the RCSM 140 and Slice Ensemble Attributor 150. In the preferred embodiment, the FRG 160 exposes a REST API at a configurable port comprising the following endpoints:'),
  blankLine(),
  pJust('GET /rca — returns the current bi-level ensemble attribution report as a structured JSON payload comprising: the candidate root cause NF identifier, the composite root cause score, the slice breadth metric, the isolation type classification, a per-slice attribution table (enumerating the causal path weight, NF presence indicator, and slice contribution for each registered slice), pipeline health metrics (cycle count, buffer fill percentage, uptime), and a list of any active faults.'),
  blankLine(),
  pJust('POST /inject — accepts a fault injection command specifying a target NF and fault type, and triggers the corresponding fault in the 5G network for evaluation purposes.'),
  blankLine(),
  pJust('GET /health — returns a lightweight health payload comprising pipeline running status, cycle count, buffer fill percentage, and uptime.'),
  blankLine(),

  // 7. RAE
  h2('7. Remediation Action Engine (RAE) 170'),
  pJust('The RAE 170 implements confidence-gated remediation: it selects and executes a remediation action only when the composite root cause score of the candidate root cause NF exceeds a configurable confidence threshold (default: 0.5). Below this threshold, the RAE 170 defers action and logs the attribution report for human review.'),
  blankLine(),
  pJust('When the confidence gate is satisfied, the RAE 170 selects a remediation action from a predefined taxonomy based on the isolation type classification produced by the Slice Ensemble Attributor 150:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'raelist', level: 0 },
    children: [new TextRun({ text: 'restart_pod — issued when the isolation type is "infrastructure-wide" and the container state of the candidate root cause NF indicates an abnormal lifecycle state. This action triggers a container restart of the candidate NF process.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'raelist', level: 0 },
    children: [new TextRun({ text: 'rollback_config — issued when the isolation type is "slice-isolated" and the fault pattern is consistent with a configuration change that affected only a subset of slice bindings. This action reverts the most recent configuration change applied to the candidate NF.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 80 },
    numbering: { reference: 'raelist', level: 0 },
    children: [new TextRun({ text: 'scale_out — issued when the composite root cause score is elevated but the isolation type is "slice-isolated" and no abnormal container state is detected, suggesting resource saturation rather than process failure.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),
  pJust('After executing the remediation action, the RAE 170 observes post-remediation outcome telemetry (KPI recovery, container state normalization) and supplies this outcome data to the DCGM 130 for recalibration of the first-level DAG edge weights. This feedback loop enables continuous improvement of the causal model without requiring labeled training data.'),
  blankLine(),

  // 8. Preferred Embodiment Operation
  h2('8. Operation of the Preferred Embodiment'),
  pJust('In normal operation, the system 100 executes the following sequence in a continuous pipeline loop:'),
  blankLine(),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The MTIE 110 continuously polls telemetry from all registered NFs and writes normalized samples into the ring buffer.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'At each cycle, the CIE 120 reads the ring buffer and applies Granger causality analysis to all ordered NF pairs, constructing the first-level DAG.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The DCGM 130 prunes statistically insignificant edges from the first-level DAG.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The RCSM 140 computes composite root cause scores for all NFs and identifies the candidate root cause NF.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The Slice Ensemble Attributor 150 computes the slice breadth metric and isolation type for the candidate root cause NF.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The FRG 160 assembles and publishes the bi-level ensemble attribution report.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'If the composite root cause score exceeds the confidence threshold, the RAE 170 selects and executes a remediation action.', size: pt(12), font: 'Arial' })]
  }),
  new Paragraph({
    spacing: { before: 40, after: 60 },
    numbering: { reference: 'steplist', level: 0 },
    children: [new TextRun({ text: 'The RAE 170 supplies outcome telemetry to the DCGM 130 for recalibration of the first-level DAG, completing the cycle.', size: pt(12), font: 'Arial' })]
  }),
  blankLine(),

  // 9. Equivalents
  h2('9. Equivalents and Scope'),
  pJust('While the foregoing describes preferred embodiments of the invention, the claims are not limited to the specific implementations described herein. Variations, modifications, and equivalents that would be apparent to one of ordinary skill in the art are within the scope of the claims. For example, the Granger causality analysis of the preferred embodiment may be replaced or supplemented with other causal discovery algorithms, including PCMCI (Peter-Clark Momentary Conditional Independence), LiNGAM, or causal Bayesian network structure learning, provided that the resulting causal model supports the construction of a directed acyclic graph suitable for the composite root cause scoring of Section 4. The specific network function types described herein (AMF, SMF, PCF, UDM, NRF) are exemplary and non-limiting; the invention applies to any set of networked software functions whose operational interdependencies can be modeled as a causal DAG.'),
  blankLine(),

  pageBreak(),

  // ── CLAIMS ─────────────────────────────────────────────────────────────
  h1('CLAIMS'),
  p('What is claimed is:'),
  blankLine(),
  ...claims,

  pageBreak(),

  // ── ABSTRACT ────────────────────────────────────────────────────────────
  h1('ABSTRACT'),
  pJust('A computer-implemented method and system for autonomous root cause attribution in a fifth-generation (5G) telecommunications network uses a bi-level causal directed acyclic graph (DAG) architecture. A first level operates at the network function (NF) layer: a Causal Inference Engine (CIE) constructs a causal DAG from multi-source telemetry using Granger causality analysis, a Dynamic Causal Graph Manager (DCGM) prunes and recalibrates the DAG based on remediation outcomes, and a Root Cause Scoring Module (RCSM) computes composite root cause scores integrating Granger temporal precedence, topology centrality, and infrastructure state signals. A second level operates at the network slice layer: a Slice Ensemble Attributor constructs per-slice sub-DAGs and computes a slice breadth metric and isolation type classification for the candidate root cause NF identified at the first level. A bi-level ensemble attribution report fusing both levels enables discrimination of slice-isolated faults from infrastructure-wide faults that produce identical first-level scores, enabling correct remediation action selection. A confidence-gated Remediation Action Engine (RAE) executes remediation actions and recalibrates the first-level DAG based on outcomes. The method operates continuously without labeled training data or manually authored fault signatures.'),

];

// ─── DOCUMENT ASSEMBLY ─────────────────────────────────────────────────────

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: 'Arial', size: pt(12) } }
    },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: pt(14), bold: true, font: 'Arial', color: '000000' },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 }
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: pt(13), bold: true, font: 'Arial', color: '000000' },
        paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1 }
      },
    ]
  },
  numbering: {
    config: [
      {
        reference: 'priorbullets',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
      {
        reference: 'modulelist',
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
      {
        reference: 'raelist',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
      {
        reference: 'steplist',
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          children: [
            new TextRun({ text: 'CAUSAL5G — NON-PROVISIONAL PATENT APPLICATION   ', size: pt(9), font: 'Arial' }),
            new TextRun({ text: 'DRAFT — ATTORNEY-CLIENT PRIVILEGED — NOT FOR FILING', size: pt(9), font: 'Arial', italics: true })
          ],
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: '888888' } }
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: 'Page ', size: pt(9), font: 'Arial' }),
            new TextRun({ text: PageNumber.CURRENT, size: pt(9), font: 'Arial', children: [PageNumber.CURRENT] })
          ]
        })]
      })
    },
    children: specChildren
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/sessions/wonderful-dreamy-cori/mnt/outputs/Causal5G_NonProvisional_Patent_DRAFT.docx', buf);
  console.log('Written: Causal5G_NonProvisional_Patent_DRAFT.docx');
}).catch(err => { console.error(err); process.exit(1); });

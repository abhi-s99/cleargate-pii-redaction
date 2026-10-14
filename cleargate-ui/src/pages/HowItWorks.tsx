import React from 'react';
import {
  Shield,
  Lock,
  AlertTriangle,
  ArrowRight,
  FileCheck,
  CheckCircle2,
  XCircle,
  Cpu,
  Layers,
  FileWarning,
} from 'lucide-react';
import { Link } from 'react-router-dom';

export const HowItWorksPage: React.FC = () => {
  return (
    <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1 space-y-16">
      {/* Page Header */}
      <div className="max-w-3xl space-y-4">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-border text-xs font-mono text-accent">
          <Shield className="w-3.5 h-3.5" />
          <span>System Architecture & Verification Proofs</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-heading font-extrabold text-text tracking-tight">
          How ClearGate Works
        </h1>
        <p className="text-base text-text-muted leading-relaxed">
          ClearGate sits as a privacy boundary between business documents and AI models. It enforces deterministic redaction, independent verification, and a fail-closed gating architecture.
        </p>
      </div>

      {/* 1. The 8-Stage Pipeline (Section 5.6) */}
      <section className="space-y-6">
        <div className="border-b border-border pb-3">
          <span className="text-xs font-mono uppercase text-accent font-semibold">
            Sequential Pipeline
          </span>
          <h2 className="text-2xl font-heading font-bold text-text mt-1">
            The 8-Stage Document Lifecycle
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            {
              step: '1. Validate',
              desc: 'Enforce format whitelist (.pdf, .docx, .pptx) and reject encrypted or malformed archives synchronously.',
              icon: <FileCheck className="w-5 h-5 text-accent" />,
            },
            {
              step: '2. Extract',
              desc: 'Deconstruct office structures (paragraphs, tables, slides) and execute offline Tesseract OCR on raster regions.',
              icon: <Layers className="w-5 h-5 text-accent" />,
            },
            {
              step: '3. Detect',
              desc: 'Run regex patterns, contextual heuristics, and vision classifiers to identify personal identifiers.',
              icon: <Cpu className="w-5 h-5 text-accent" />,
            },
            {
              step: '4. Resolve',
              desc: 'Route uncertain detections to privacy reviewer queue. Strict policy forbids rejecting deterministic high-risk items.',
              icon: <AlertTriangle className="w-5 h-5 text-accent" />,
            },
            {
              step: '5. Redact',
              desc: 'Substitute verified spans with structured tokens ([PERSON_1], [SSN]) and burn black masks into images.',
              icon: <Lock className="w-5 h-5 text-accent" />,
            },
            {
              step: '6. Verify',
              desc: 'Independent scanner inspects sanitized output to detect any leaked values or surviving unreadable regions.',
              icon: <CheckCircle2 className="w-5 h-5 text-accent" />,
            },
            {
              step: '7. Gate',
              desc: 'Cryptographic policy check evaluates verification results. Releases safe handle or blocks document.',
              icon: <Shield className="w-5 h-5 text-accent" />,
            },
            {
              step: '8. Handoff',
              desc: 'Transmit sanitized text to downstream AI model. The model never touches unverified original documents.',
              icon: <ArrowRight className="w-5 h-5 text-accent" />,
            },
          ].map((item, idx) => (
            <div
              key={idx}
              className="bg-surface border border-border rounded-lg p-5 flex flex-col justify-between space-y-3 shadow-card"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  {item.icon}
                  <span className="font-mono text-xs text-text-muted">Stage {idx + 1}</span>
                </div>
                <h3 className="font-heading font-semibold text-text text-sm">{item.step}</h3>
                <p className="text-xs text-text-muted leading-relaxed">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 2. State Machine Diagram Drawn as SVG/CSS (Section 5.6) */}
      <section id="states" className="space-y-6">
        <div className="border-b border-border pb-3">
          <span className="text-xs font-mono uppercase text-accent font-semibold">
            State Machine Specification
          </span>
          <h2 className="text-2xl font-heading font-bold text-text mt-1">
            Server-Enforced Job State Transitions
          </h2>
          <p className="text-xs text-text-muted mt-1">
            Zero state inference occurs in the client. State transitions are strictly enforced by the backend gate.
          </p>
        </div>

        <div className="bg-surface border border-border rounded-lg p-6 lg:p-8 shadow-card overflow-x-auto">
          {/* SVG Architecture Diagram */}
          <svg
            viewBox="0 0 920 420"
            className="w-full min-w-[760px] text-xs font-mono"
            aria-label="ClearGate Job State Machine Diagram"
          >
            <defs>
              <marker
                id="arrowhead"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="var(--text-muted)" />
              </marker>
              <marker
                id="arrowhead-accent"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="var(--accent)" />
              </marker>
              <marker
                id="arrowhead-safe"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="var(--status-safe)" />
              </marker>
              <marker
                id="arrowhead-failed"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="var(--status-failed)" />
              </marker>
            </defs>

            {/* State Node: RECEIVED */}
            <rect x="30" y="160" width="130" height="60" rx="8" fill="var(--surface-raised)" stroke="var(--border)" strokeWidth="2" />
            <text x="95" y="195" fill="var(--text)" textAnchor="middle" fontWeight="bold" fontSize="13">RECEIVED</text>

            {/* State Node: PROCESSING */}
            <rect x="250" y="160" width="150" height="60" rx="8" fill="var(--surface-raised)" stroke="var(--status-processing)" strokeWidth="2" />
            <text x="325" y="195" fill="var(--status-processing)" textAnchor="middle" fontWeight="bold" fontSize="13">PROCESSING</text>

            {/* State Node: REVIEW_REQUIRED */}
            <rect x="490" y="40" width="170" height="60" rx="8" fill="var(--surface-raised)" stroke="var(--status-review)" strokeWidth="2" />
            <text x="575" y="75" fill="var(--status-review)" textAnchor="middle" fontWeight="bold" fontSize="13">REVIEW_REQUIRED</text>

            {/* Terminal State Node: VALIDATED_SAFE */}
            <rect x="740" y="160" width="160" height="60" rx="8" fill="var(--surface-raised)" stroke="var(--status-safe)" strokeWidth="3" />
            <text x="820" y="188" fill="var(--status-safe)" textAnchor="middle" fontWeight="bold" fontSize="12">VALIDATED_SAFE</text>
            <text x="820" y="206" fill="var(--text-muted)" textAnchor="middle" fontSize="10">[Terminal Safe]</text>

            {/* Terminal State Node: BLOCKED */}
            <rect x="490" y="280" width="150" height="60" rx="8" fill="var(--surface-raised)" stroke="var(--status-blocked)" strokeWidth="3" />
            <text x="565" y="308" fill="var(--status-blocked)" textAnchor="middle" fontWeight="bold" fontSize="12">BLOCKED</text>
            <text x="565" y="326" fill="var(--text-muted)" textAnchor="middle" fontSize="10">[Terminal Gate]</text>

            {/* Terminal State Node: FAILED */}
            <rect x="180" y="340" width="140" height="55" rx="8" fill="var(--surface-raised)" stroke="var(--status-failed)" strokeWidth="3" />
            <text x="250" y="367" fill="var(--status-failed)" textAnchor="middle" fontWeight="bold" fontSize="12">FAILED</text>
            <text x="250" y="383" fill="var(--text-muted)" textAnchor="middle" fontSize="10">[Terminal Error]</text>

            {/* Transitions Lines & Labels */}
            {/* RECEIVED -> PROCESSING */}
            <path d="M 160 190 L 250 190" stroke="var(--text-muted)" strokeWidth="2" markerEnd="url(#arrowhead)" />
            <text x="205" y="180" fill="var(--text-muted)" textAnchor="middle" fontSize="10">dispatch</text>

            {/* RECEIVED -> FAILED */}
            <path d="M 95 220 L 95 365 L 180 365" fill="none" stroke="var(--status-failed)" strokeWidth="1.5" strokeDasharray="4" markerEnd="url(#arrowhead-failed)" />
            <text x="135" y="355" fill="var(--status-failed)" textAnchor="middle" fontSize="10">validation err</text>

            {/* PROCESSING -> REVIEW_REQUIRED */}
            <path d="M 325 160 L 325 70 L 490 70" fill="none" stroke="var(--status-review)" strokeWidth="2" markerEnd="url(#arrowhead)" />
            <text x="410" y="60" fill="var(--status-review)" textAnchor="middle" fontSize="10">uncertain pii / scan</text>

            {/* REVIEW_REQUIRED -> PROCESSING (after decisions) */}
            <path d="M 490 90 L 420 90 L 420 170 L 400 170" fill="none" stroke="var(--accent)" strokeWidth="2" markerEnd="url(#arrowhead-accent)" />
            <text x="445" y="130" fill="var(--accent)" fontSize="10">re-verify loop</text>

            {/* REVIEW_REQUIRED -> BLOCKED */}
            <path d="M 575 100 L 575 280" fill="none" stroke="var(--status-blocked)" strokeWidth="2" markerEnd="url(#arrowhead)" />
            <text x="635" y="190" fill="var(--status-blocked)" textAnchor="middle" fontSize="10">reject doc</text>

            {/* PROCESSING -> VALIDATED_SAFE */}
            <path d="M 400 190 L 740 190" stroke="var(--status-safe)" strokeWidth="2.5" markerEnd="url(#arrowhead-safe)" />
            <text x="560" y="180" fill="var(--status-safe)" textAnchor="middle" fontSize="11" fontWeight="bold">verification passed</text>

            {/* PROCESSING -> BLOCKED */}
            <path d="M 370 220 L 370 310 L 490 310" fill="none" stroke="var(--status-blocked)" strokeWidth="2" markerEnd="url(#arrowhead)" />
            <text x="430" y="300" fill="var(--status-blocked)" textAnchor="middle" fontSize="10">leak detected</text>

            {/* PROCESSING -> FAILED */}
            <path d="M 300 220 L 300 340" stroke="var(--status-failed)" strokeWidth="1.5" strokeDasharray="4" markerEnd="url(#arrowhead-failed)" />
            <text x="270" y="270" fill="var(--status-failed)" textAnchor="middle" fontSize="10">ocr crash</text>
          </svg>
        </div>
      </section>

      {/* 3. Fail-Closed Explainer (Section 5.6) */}
      <section id="fail-closed" className="bg-bg-alt border border-border rounded-lg p-8 space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-status-blocked-bg text-status-blocked flex items-center justify-center shrink-0">
            <XCircle className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs font-mono uppercase text-status-blocked font-semibold">
              Zero-Trust Isolation
            </span>
            <h2 className="text-xl font-heading font-bold text-text">
              Fail-Closed Verification Principles
            </h2>
          </div>
        </div>

        <blockquote className="p-4 rounded border-l-4 border-status-blocked bg-surface text-sm text-text italic">
          &ldquo;An unread page, an unapplied redaction, or a surviving value blocks the document.&rdquo;
        </blockquote>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs text-text-muted">
          <div className="space-y-1.5 p-4 rounded bg-surface border border-border">
            <h4 className="font-semibold text-text text-sm flex items-center gap-1.5">
              <FileWarning className="w-4 h-4 text-status-blocked" />
              <span>Unread Raster Regions</span>
            </h4>
            <p className="leading-relaxed">
              If an OCR scanner fails on a degraded page or low-contrast text, the system cannot verify safety. The page is flagged or blocked rather than passed unchecked.
            </p>
          </div>

          <div className="space-y-1.5 p-4 rounded bg-surface border border-border">
            <h4 className="font-semibold text-text text-sm flex items-center gap-1.5">
              <Lock className="w-4 h-4 text-status-blocked" />
              <span>Independent Verification</span>
            </h4>
            <p className="leading-relaxed">
              Redactions are verified by an independent secondary scanner. If a tokenized identifier pattern survives into the sanitized stream, the job transitions to BLOCKED.
            </p>
          </div>

          <div className="space-y-1.5 p-4 rounded bg-surface border border-border">
            <h4 className="font-semibold text-text text-sm flex items-center gap-1.5">
              <Shield className="w-4 h-4 text-status-blocked" />
              <span>Zero Privacy Logic in Client</span>
            </h4>
            <p className="leading-relaxed">
              The web interface never decides a document is safe. Artifacts and AI handoffs are cryptographically disabled until the server returns VALIDATED_SAFE.
            </p>
          </div>
        </div>
      </section>

      {/* 4. Limitations Box (Section 5.6) */}
      <section id="limitations" className="bg-surface border border-border rounded-lg p-8 space-y-4 shadow-card">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-status-review" />
          <h2 className="font-heading font-bold text-lg text-text">
            Prototype Limitations & Safety Disclaimers
          </h2>
        </div>

        <div className="divide-y divide-border/60 text-xs text-text-muted space-y-3">
          <div className="pt-3 first:pt-0">
            <p className="font-semibold text-text">No scanner proves zero PII:</p>
            <p className="mt-0.5">
              Automated pattern detection and machine learning models reduce exposure but cannot mathematically guarantee zero residual privacy risk in unstructured natural language.
            </p>
          </div>

          <div className="pt-3">
            <p className="font-semibold text-text">OCR cannot read every region:</p>
            <p className="mt-0.5">
              Low-resolution imagery, complex graphical diagrams, and skewed scans produce OCR uncertainties. Unreadable regions are masked and escalated for human review.
            </p>
          </div>

          <div className="pt-3">
            <p className="font-semibold text-text">Prototype security posture:</p>
            <p className="mt-0.5">
              This prototype utilizes static bearer tokens and a single-tenant deployment architecture. It is built as an evaluation prototype for the Optiv Consulting case study PS-2 and is not for production use.
            </p>
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <div className="text-center pt-4">
        <Link
          to="/"
          className="inline-flex items-center gap-2 bg-accent hover:bg-accent-hover text-text-on-accent font-semibold px-6 py-3 rounded-md transition-colors shadow"
        >
          <span>Return to Document Upload</span>
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
};

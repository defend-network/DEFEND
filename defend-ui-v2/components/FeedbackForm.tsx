"use client";

import { useState } from "react";
import { X } from "lucide-react";

const FORMSPREE = "https://formspree.io/f/xjybyyqd";

type Props = {
  open: boolean;
  onClose: () => void;
  presetAnswer?: string;
  presetQuestion?: string;
};

export function FeedbackForm({ open, onClose, presetAnswer = "", presetQuestion = "" }: Props) {
  const [email, setEmail] = useState("");
  const [issue, setIssue] = useState("off_script");
  const [message, setMessage] = useState("");
  const [question, setQuestion] = useState(presetQuestion);
  const [answer, setAnswer] = useState(presetAnswer);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(FORMSPREE, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          email: email || "anonymous",
          issue_type: issue,
          message,
          user_question: question,
          ai_answer: answer,
          page: typeof window !== "undefined" ? window.location.href : "",
          _subject: `DEFEND AI feedback: ${issue}`,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Form error ${res.status}`);
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className="eyebrow">Feedback</span>
            <h2>Report a bad answer</h2>
          </div>
          <button className="icon-btn" type="button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {done ? (
          <div className="modal-success">
            <p>Received. We’ll use this to harden the model and the stack.</p>
            <button type="button" className="modal-submit" onClick={onClose}>
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="modal-form">
            <p className="muted">
              Use this when DEFEND AI errors, softens, breaks character, invents sources, or gives an
              answer that doesn’t fit the script.
            </p>

            <label>
              Issue type
              <select value={issue} onChange={(e) => setIssue(e.target.value)} required>
                <option value="off_script">Off-script / wrong tone</option>
                <option value="soft_refusal">Soft refusal / HR language</option>
                <option value="wrong_facts">Wrong facts / bad research</option>
                <option value="error">Error / 500 / failed request</option>
                <option value="other">Other</option>
              </select>
            </label>

            <label>
              Your email (optional)
              <input
                type="email"
                name="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </label>

            <label>
              What you asked
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                rows={2}
                placeholder="Paste the user question"
              />
            </label>

            <label>
              What he answered
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={4}
                placeholder="Paste the bad answer (or describe the error)"
              />
            </label>

            <label>
              Notes
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={3}
                required
                placeholder="What should have happened instead?"
              />
            </label>

            {error && <div className="admin-lock-err">{error}</div>}

            <button className="modal-submit" type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send report"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

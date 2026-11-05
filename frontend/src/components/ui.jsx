import { X } from 'lucide-react';
import { useEffect } from 'react';

// Small shared building blocks for the white console theme.

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-head">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Panel({ title, action, children, className = '', bodyClassName = 'panel-b' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panel-h">
          {title && <h2 className="section-title">{title}</h2>}
          {action}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

// Segmented control. options: [{ value, label, count? }]
export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.dot && <span className={`dot ${o.dot}`} />}
          {o.label}
          {o.count != null && <span className="count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, htmlFor, children, className = '' }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <label htmlFor={htmlFor} className="field-label">{label}</label>
      {children}
    </div>
  );
}

export function Empty({ children }) {
  return <p className="text-sm text-muted py-8 text-center">{children}</p>;
}

export function Modal({ title, children, onClose, wide = false, busy = false }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, busy]);

  return (
    <div className="fixed inset-0 bg-ink/40 backdrop-blur-[2px] z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        role="dialog" aria-modal="true" aria-label={title}
        className={`panel w-full max-h-[90vh] overflow-y-auto p-5 shadow-2xl ${wide ? 'max-w-3xl' : 'max-w-md'}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} disabled={busy} aria-label="Close dialog" className="icon-btn disabled:opacity-30">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

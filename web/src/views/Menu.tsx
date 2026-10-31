import { useEffect, useRef, useState, type ReactNode } from "react";

/** A small action menu that behaves like a real one (spec §11, mockup's Pause menu): arrow keys,
 * Home/End, Escape returns focus to the button, Tab or an outside click closes it. */
export function MenuButton({ label, buttonContent, items, id, wrapClass = "now-acts", buttonClass = "btn", buttonLabel }: {
  label: string;
  id: string;
  buttonContent: ReactNode;
  wrapClass?: string;
  buttonClass?: string;
  buttonLabel?: string;
  items: { key: string; content: ReactNode; onSelect: () => void }[];
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (open) refs.current[0]?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  const close = (refocus: boolean) => { setOpen(false); if (refocus) btn.current?.focus(); };
  const onKey = (e: React.KeyboardEvent) => {
    const list = refs.current.filter(Boolean) as HTMLButtonElement[];
    const k = list.indexOf(document.activeElement as HTMLButtonElement);
    const to = (i: number) => { e.preventDefault(); list[(i + list.length) % list.length]?.focus(); };
    if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "ArrowDown") to(k + 1);
    else if (e.key === "ArrowUp") to(k - 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(list.length - 1);
    else if (e.key === "Tab") close(false);
  };

  return (
    <span className={wrapClass} ref={wrap} onKeyDown={open ? onKey : undefined}>
      <button ref={btn} className={buttonClass} type="button" aria-haspopup="menu" aria-expanded={open} aria-controls={id}
        aria-label={buttonLabel}
        onClick={() => (open ? close(true) : setOpen(true))}>{buttonContent}</button>
      <div className="menu" id={id} role="menu" aria-label={label} hidden={!open}>
        <div className="lab" aria-hidden="true">{label}</div>
        {open && items.map((it, i) => (
          <button key={it.key} ref={(el) => { refs.current[i] = el; }} role="menuitem" tabIndex={-1} type="button"
            onClick={() => { close(true); it.onSelect(); }}>{it.content}</button>
        ))}
      </div>
    </span>
  );
}

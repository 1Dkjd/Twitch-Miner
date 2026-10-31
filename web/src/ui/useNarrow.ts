import { useEffect, useState } from "react";

/** True at phone width: the same breakpoint as app.css's phone rules. */
export function useNarrow() {
  const q = "(max-width: 720px)";
  const [m, setM] = useState(() => typeof matchMedia === "function" && matchMedia(q).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return m;
}

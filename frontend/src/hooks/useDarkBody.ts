import { useEffect } from "react";

/** The dark pages paint their own background, but overscroll and short pages would show the (white) body behind it. */
export function useDarkBody(color = "#04060f"): void {
  useEffect(() => {
    const previous = document.body.style.backgroundColor;
    document.body.style.backgroundColor = color;
    return () => {
      document.body.style.backgroundColor = previous;
    };
  }, [color]);
}

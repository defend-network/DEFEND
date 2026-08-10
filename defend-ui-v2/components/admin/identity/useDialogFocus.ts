"use client";

import { useLayoutEffect, useRef, type RefObject } from "react";

type DialogFocusOptions = {
  active?: boolean;
  containerRef: RefObject<HTMLElement | null>;
  initialFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
};

const FOCUSABLE = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function useDialogFocus({
  active = true,
  containerRef,
  initialFocusRef,
  onClose,
  returnFocusRef,
}: DialogFocusOptions) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    function focusableElements() {
      return Array.from(
        container!.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((item) => !item.hidden && item.getAttribute("aria-hidden") !== "true");
    }

    function focusInitial() {
      const initial = initialFocusRef.current;
      if (initial?.isConnected) initial.focus();
      else focusableElements()[0]?.focus();
    }

    focusInitial();

    function handleFocusIn(event: FocusEvent) {
      if (!(event.target instanceof Node) || container!.contains(event.target)) return;
      focusInitial();
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        container!.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const focused = document.activeElement;
      if (event.shiftKey && (focused === first || !container!.contains(focused))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (focused === last || !container!.contains(focused))) {
        event.preventDefault();
        first.focus();
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    document.addEventListener("focusin", handleFocusIn);
    return () => {
      container.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("focusin", handleFocusIn);
      const target = returnFocusRef?.current ?? opener;
      if (target?.isConnected) target.focus();
    };
  }, [active, containerRef, initialFocusRef, returnFocusRef]);
}

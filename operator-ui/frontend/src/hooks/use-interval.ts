// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef } from "react";

/** Run `callback` every `delayMs`, like the original UI's setInterval (no pausing, no catch-up). */
export function useInterval(callback: () => void, delayMs: number) {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  }, [callback]);

  useEffect(() => {
    const timer = setInterval(() => saved.current(), delayMs);
    return () => clearInterval(timer);
  }, [delayMs]);
}

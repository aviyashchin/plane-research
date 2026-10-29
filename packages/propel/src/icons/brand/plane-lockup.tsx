/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
import type { ISvgIcons } from "../type";

export function PlaneLockup({ width = "240", height = "48", className, color = "currentColor", ...rest }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 240 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...rest}
    >
      <line x1="23" y1="11" x2="11" y2="33" stroke={color} strokeWidth="1" strokeLinecap="round" />
      <line x1="25" y1="11" x2="37" y2="33" stroke={color} strokeWidth="1" strokeLinecap="round" />
      <line x1="11" y1="36" x2="37" y2="36" stroke="#c8102e" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="24" cy="8" r="2.6" fill="none" stroke={color} strokeWidth="1" strokeDasharray="1.4 1" />
      <circle cx="10" cy="36" r="2.6" fill={color} />
      <circle cx="38" cy="36" r="2.6" fill="none" stroke={color} strokeWidth="1" />
      <text x="50" y="31" fill={color} fontFamily="system-ui, sans-serif" fontSize="24" fontWeight="600">
        Subconscious
      </text>
    </svg>
  );
}

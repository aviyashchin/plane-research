/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import brandMark from "@/app/assets/subconscious-mark.svg?url";

export function LogoSpinner() {
  return (
    <div className="flex items-center justify-center">
      <img src={brandMark} alt="Subconscious" className="h-6 w-auto object-contain sm:h-11" />
    </div>
  );
}

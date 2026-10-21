/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { observer } from "mobx-react";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { ResearchIntegrations } from "@/components/integration/research";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";

function WorkspaceIntegrationsPage() {
  const { currentWorkspace } = useWorkspace();
  const { allowPermissions } = useUserPermissions();
  if (!allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE))
    return <NotAuthorizedView section="settings" className="h-auto" />;
  return (
    <>
      <PageHead title={`${currentWorkspace?.name ?? "Workspace"} - Research tools`} />
      <section className="w-full overflow-y-auto">
        {currentWorkspace && <ResearchIntegrations slug={currentWorkspace.slug} />}
      </section>
    </>
  );
}
export default observer(WorkspaceIntegrationsPage);

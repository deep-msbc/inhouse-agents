import React, { useRef } from "react";
import { ConfigurableDashboard, type ConfigurableDashboardHandle, } from "@msbc/config-ui";
import { UserList4Config } from "./UserList4.config";

export const UserList4: React.FC = () => {
  const ref = useRef<ConfigurableDashboardHandle>(null);

  return (
    <React.Fragment>
      <ConfigurableDashboard
        ref={ref}
        config={UserList4Config}
        onSearch={(value) => console.log("Search:", value)}
        onFilterChange={(i, v) => console.log("Filter changed:", i, v)}
      />
    </React.Fragment>
  );
};
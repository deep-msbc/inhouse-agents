import { ConfigurableDashboard, type ConfigurableDashboardHandle } from "@msbc/config-ui";
import { UserList5Config } from "./UserList5Config";
import React, { useRef } from "react";

export const UserList5: React.FC = () => {
  const ref = useRef<ConfigurableDashboardHandle>(null);

  return (
    <React.Fragment>
      <ConfigurableDashboard
        ref={ref}
        config={UserList5Config}
        onSearch={(value) => console.log("Search:", value)}
        onFilterChange={(i, v) => console.log("Filter changed:", i, v)}
      />
    </React.Fragment>
  );
};

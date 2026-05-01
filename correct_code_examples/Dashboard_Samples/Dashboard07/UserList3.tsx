import React, { useRef } from "react";
import { ConfigurableDashboard, type ConfigurableDashboardHandle, } from "@msbc/config-ui";
import { UserList3Config } from "./UserList3.config";

export const UserList3 : React.FC = () => {
  const ref = useRef<ConfigurableDashboardHandle>(null);

  return (
    <React.Fragment>
      <ConfigurableDashboard
        ref={ref}
        config={UserList3Config}
        onSearch={(value) => console.log("Search:", value)}
        onFilterChange={(i, v) => console.log("Filter changed:", i, v)}
      />
    </React.Fragment>
  );
};
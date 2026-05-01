import React, { useRef } from 'react';
import { ConfigurableDashboard, type ConfigurableDashboardHandle } from '@msbc/config-ui';
import { dashboard3config } from './dashboard3config';

export const Dashboard3: React.FC = () => {
  const ref = useRef<ConfigurableDashboardHandle>(null);

  return (
    <React.Fragment>
      <ConfigurableDashboard
        ref={ref}
        config={dashboard3config}
        onSearch={(value) => console.log('Search:', value)}
        onFilterChange={(i, v) => console.log('Filter changed:', i, v)}
      />
    </React.Fragment>
  );
};

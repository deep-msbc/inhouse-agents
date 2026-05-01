import React, { useRef, useState } from 'react';
import { ConfigurableDashboard, type ConfigurableDashboardHandle } from '@msbc/config-ui';
import { dashboard4config } from './dashboard4config';
import { Dropdown, Modal } from '@msbc/react-toolkit';

export const Dashboard4: React.FC = () => {
  const ref = useRef<ConfigurableDashboardHandle>(null);
  const [show, setshow] = useState(false);

  return (
    <React.Fragment>
      <ConfigurableDashboard
        ref={ref}
        config={dashboard4config}
        onSearch={(value) => console.log('Search:', value)}
        onFilterChange={(i, v) => console.log('Filter changed:', i, v)}
      />
      <Modal show={show} onClose={() => setshow(false)} title="Modal">
        <Dropdown
          api={{
            url: 'https://jsonplaceholder.typicode.com/users',
            autoFetch: true,
          }}
          labelKey="display_name"
          valueKey="id"
          menuPortalTarget={document.body}
        />
      </Modal>
      {/* <button style={{ padding:"10px 20px ",borderRadius:"15px", border:"none", backgroundColor:"crimson", color:"whitesmoke", fontSize:""}}> */}
        {/* filters
      </button> */}
    </React.Fragment>
  );
};

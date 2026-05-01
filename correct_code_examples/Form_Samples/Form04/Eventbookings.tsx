import type { Eventbooking } from './types';
import { eventschema } from './Form04config';
import { ConfigurableForm } from '@msbc/config-ui';

export const Eventbookings = () => {
  return (
    <div style={{ padding: '2rem' }}>
      <ConfigurableForm<Eventbooking>
        config={eventschema}
        onSubmit={(data) => console.log(data)}
        primaryButtonProps={{
          text: 'Request Booking',
          variant: 'secondary',
          size: 'large',
        }}
      />
    </div>
  );
};

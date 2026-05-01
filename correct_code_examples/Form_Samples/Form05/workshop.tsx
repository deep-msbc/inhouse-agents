import { ConfigurableForm } from '@msbc/config-ui';
import { userschema } from './Formconfig';
import type { Registration } from './types';
import { useApiRequest } from '@msbc/data-layer';

export const workshop = () => {
  const { execute } = useApiRequest({
    url: '',
    method: 'post',
    autoFetch: false,
  });

  const handleOnSubmit = (data: Registration) => {
    execute({
      body: data,
    })
      .then((response) => {
        console.log(response);
      })
      .catch((err) => {
        console.log(err);
      });
  };

  return (
    <div style={{ padding: '2rem' }}>
      <ConfigurableForm<Registration>
        config={userschema}
        onSubmit={handleOnSubmit}
        actionButtonPosition="bottom"
        primaryButtonProps={{
          text: 'Request Booking',
          variant: 'primary',
          size: 'small',
        }}
      />
    </div>
  );
};

import { userFormConfig } from './form3config';
import type { UserFormValues } from './types';
import { ConfigurableForm } from '@msbc/config-ui';

export const Form03 = () => {
  const handleSubmit = (data: UserFormValues) => {
    console.log('Form Submitted:', data);

    const formData = new FormData();

    // Profile picture
    data.profilePicture?.forEach((file) => formData.append('profilePicture', file));

    // Documents
    data.documents?.forEach((doc, idx) => {
      doc.file?.forEach((file) => formData.append(`documents[${idx}]`, file));
      formData.append(`documentsType[${idx}]`, doc.type);
    });

    formData.append('birthDate', data.birthDate || '');

    fetch('/api/upload', { method: 'POST', body: formData });
  };

  return (
    <div style={{ padding: '2rem' }}>
      <ConfigurableForm<UserFormValues>
        config={userFormConfig}
        onSubmit={handleSubmit}
        hasSecondaryButton={true}
        primaryButtonProps={{ text: 'Save User' }}
        secondaryButtonProps={{ text: 'Reset Form' }}
      />
    </div>
  );
};

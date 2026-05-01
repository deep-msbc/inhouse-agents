import type { JSONFormSchema } from '@msbc/config-ui';
import type { UserFormValues } from './types';

export const userFormConfig: JSONFormSchema<UserFormValues> = {
  title: 'Advanced User Form',
  description: 'Form with file uploads, repeatable sections, conditional fields, and date picker.',
  layout: { columns: 2 },
  sections: [
    {
      type: 'group',
      title: 'Personal Info',
      layout: { columns: 1 },
      sections: [
        {
          title: 'Basic Details',
          fields: [
            { name: 'firstName', label: 'First Name', type: 'text', colSpan: 1 },
            { name: 'lastName', label: 'Last Name', type: 'text', colSpan: 1 },
            { name: 'email', label: 'Email', type: 'email', colSpan: 2 },
            { name: 'profilePicture', label: 'Profile Picture', type: 'fileUpload', colSpan: 2 },
            { name: 'birthDate', label: 'Date of Birth', type: 'date', colSpan: 2, value: null }, // Date Picker
          ],
        },
      ],
    },
    {
      repeatable: true,
      name: 'documents',
      title: 'Documents Upload',
      addLabel: 'Add Document',
      removeLabel: 'Remove Document',
      layout: { columns: 4 },
      fields: [
        { name: 'type', label: 'Document Type', type: 'text' },
        { name: 'file', label: 'Upload File', type: 'fileUpload' },
      ],
    },
    {
      title: 'Preferences',
      type: 'section',
      fields: [
        {
          name: 'subscribe',
          label: 'Subscribe to Newsletter',
          type: 'checkbox',
          options: [
            {
              label: 'test',
              value: 'false',
            },
          ],
        },
        {
          name: 'additionalInfo',
          label: 'Additional Info',
          type: 'textarea',
          visibleIf: {
            field: 'subscribe',
            operator: 'exists',
            value: 'false',
          },
        },
      ],
    },
  ],
};

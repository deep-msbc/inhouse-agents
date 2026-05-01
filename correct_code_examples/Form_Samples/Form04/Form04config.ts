import type { JSONFormSchema } from '@msbc/config-ui';
import type { Eventbooking } from './types';
export const eventschema: JSONFormSchema<Eventbooking> = {
  title: 'Event Booking System',
  description: 'We are Here To Manage Your Events ',
  layout: {
    columns: 2,
  },
  sections: [
    {
      type: 'group',
      title: 'Customer Details',
      layout: { columns: 1 },
      sections: [
        {
          title: 'Basic Information',
          layout: { columns: 1 },
          fields: [
            {
              name: 'customername',
              type: 'text',
              label: 'Customer Name',
              validation: {
                required: { message: 'Please Enter the name' },
              },
            },
            {
              name: 'email',
              type: 'email',
              label: 'Email',
              validation: {
                required: { message: 'Email is required' },
                pattern: {
                  value: '/^[^\s@]+@[^\s@]+\.[^\s@]+$/',
                  message: 'Enter valid email',
                },
              },
            },
            {
              name: 'eventdate',
              label: 'Event Date',
              type: 'date',
              value: null,
              colSpan: 2,
            },
          ],
        },
      ],
    },
    // ================= CONDITIONAL SECTION =================
    {
      title: 'Catering',
      type: 'section',
      fields: [
        {
          name: 'cateringRequired',
          label: 'Require Catering?',
          type: 'radio',
          options: [
            { label: 'No', value: 'false' },
            { label: 'Yes', value: 'true' },
          ],
        },

        {
          name: 'menuType',
          label: 'Menu Type',
          type: 'select',
          options: [
            { label: 'Veg', value: 'veg' },
            { label: 'Non-Veg', value: 'nonveg' },
            { label: 'Jain', value: 'jain' },
          ],
        },
        {
          colSpan: 3,
          name: 'addwishlist',
          label: "Add your's Wishlist",
          type: 'textarea',
          visibleIf: {
            field: 'cateringRequired',
            operator: 'equals',
            value: 'true',
          },
        },
        {
          colSpan: 2,
          name: 'addlocation',
          label: 'add you location',
          type: 'map',
          apiKey: '',
        },
      ],
    },
    // ================= FILE UPLOAD =================
    {
      title: 'Additional Attachments',
      fields: [
        {
          name: 'attachments',
          label: 'Upload Files',
          type: 'fileUpload',
          colSpan: 1,
        },
      ],
    },
  ],
};

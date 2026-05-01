import type { JSONFormSchema } from '@msbc/config-ui';
import type { Registration } from './types';

export const userschema: JSONFormSchema<Registration> = {
  title: 'Conference Registration Form',
  description: 'we ready to grow with us',
  layout: { columns: 2 },
  sections: [
    {
      type: 'group',
      title: 'Basic Information Section',
      layout: { columns: 1 },
      sections: [
        {
          title: 'Enter your details',
          fields: [
            {
              name: 'firstname',
              type: 'text',
              label: 'Firstname',
              validation: {
                required: { message: 'please enter name' },
              },
            },
            {
              name: 'lastname',
              type: 'text',
              label: 'Lastname',
              validation: {
                required: { message: 'please enter name' },
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
              name: 'doa',
              label: 'Attending Date',
              type: 'date',
              value: null,
              validation:{
                required:{message:"Please select the Date"}
              }
            },
            {
              name: 'attandance',
              label: 'Attendance Type',
              type: 'radio',
              options: [
                { label: 'online', value: 'online' },
                { label: 'offline', value: 'offline' },
              ],
              validation:{
                required:{message:"choose the attanding mode "}
              }
            },
            {
              name: 'virtual',
              label: 'Platform Preference',
              type: 'select',
              options: [
                { label: 'Zoom', value: 'zoom' },
                { label: 'Google Meet', value: 'googleMeet' },
                { label: 'Teams', value: 'teams' },
              ],
              visibleIf: {
                field: 'attandance',
                value: 'online',
                operator: 'equals',
              },
              validation:{
                required:{message:"Select the Platform"}
              }
            },
          ],
        },
      ],
    },
    {
      type: 'group',
      title: 'Workshop Information Section',
      layout: { columns: 1 },

      sections: [
        {
          title: 'Workshop Selection',

          fields: [
            {
              name: 'workshop',
              type: 'checkbox',
              isMultiple: true,

              label: 'Select Workshops',
              options: [
                { label: 'React.js', value: 'react' },
                { label: 'Node.js', value: 'node' },
                { label: 'AI/ML', value: 'aiml' },
                { label: 'System Design', value: 'systemDesign' },
                { label: 'AI Basics', value: 'aiBasics' },
              ],
              validation: {
                required: { message: 'must select at least one' },
              },
            },
            {
              name: 'experience',
              type: 'select',
              label: 'Experience Level',
              options: [
                { label: 'Beginner', value: 'beginner' },
                { label: 'Intermediate', value: 'intermediate' },
              ],
            },
            {
              name: 'certificate',
              label: 'Need cetificate ?',
              type: 'checkbox',
              options: [
                {
                  label: 'Yes',
                  value: 'yes',
                },
                {
                  label: 'No',
                  value: 'no',
                },
              ],
            },
            {
              name: 'photo',
              type: 'fileUpload',
              label: 'Upload photo fro the certicticate ',
              visibleIf: {
                field: 'certificate',
                value: 'yes',
                operator: 'equals',
              },
            },
          ],
        },
      ],
    },
    {
      name: 'participants',
      title: 'Participant Details',
      type: 'repeatable',
      repeatable: true,
      addLabel: 'Add Participant',
      removeLabel: 'Remove',
      fields: [
        {
          name: 'name',
          type: 'text',
          label: 'Participant Name',
          validation: {
            required: { message: 'name is required' },
          },
        },
        {
          name: 'email',
          type: 'email',
          label: 'Participant Email',
          validation: {
            required: { message: 'email is required' },
          },
        },
        {
          name: 'workshopChoice',
          type: "select",
          
          rowSpan:3,
          options: [
                { label: 'React.js', value: 'react' },
                { label: 'Node.js', value: 'node' },
                { label: 'AI/ML', value: 'aiml' },
                { label: 'System Design', value: 'systemDesign' },
                { label: 'AI Basics', value: 'aiBasics' },
              ],

          label: 'Workshop Selected',
          validation: {
            required: { message: 'Please select the workshopChoice'},
          },
        },
      ],
    },
  ],
};

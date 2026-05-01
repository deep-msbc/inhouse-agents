import type { JSONFormSchema } from '@msbc/config-ui'
import type { Level3FormSchema } from './level3form.types';

export const Level3Form: JSONFormSchema<Level3FormSchema> = {
  title: "A Detailed User Form",
  fields: [
    {
      type: "text",
      name: "fullName",
      label: "Full Name",
      validation: {
        required: true,
        pattern: {
          value: "/^[A-Za-z\s]+$/",
          message: "Only alphabets allowed"
        }
      }

    },
    {
      type: "text",
      name: "email",
      label: "Email",
      validation: {
        required: true,
        pattern: {
          value: "^[^@]+@[^@]+\\.[^@]+$",
          message: "Invalid email",
        },
      },
    },
    {
      type: "text",
      name: "age",
      label: "Age",
      validation: {
        required: true,
        min: { value: 18, message: "Minimum 18" },
      },
    },
    {
      name: "Address",
      type: "text",
      label: "Address"
    },
    {
      type: "radio",
      name: "gender",
      label: "Gender",
      options: [
        { label: "Male", value: "M" },
        { label: "Female", value: "F" },
      ],
      validation: {
        required: true,
      },
    },
    {
      type: "checkbox",
      name: "hobbies",
      isMultiple : true,
      label: "Hobbies",
      options: [
        { label: "Music", value: "music" },
        { label: "Sports", value: "sports" },
        { label: "Art", value: "Art" },
        { label: "Gardening", value: "Gardening" },
        { label: "Travelling", value: "Travelling" },
        { label: "Reading", value: "Reading" },
        { label: "Dance", value: "Dance" },
      ],
      
      validation: {
        required: true,
      },
    },
    {
      type: "select",
      name: "country",
      
      label: "Country",
      options: [
        { label: "India", value: "IN" },
        { label: "USA", value: "US" },
        { label: "United Kingdom", value: "Uk" },
        { label: "Iran", value: "IR" },
        { label: "Israel", value: "IS" },
        { label: "Germany", value: "GR" },
        { label: "China", value: "CH" },
        { label: "NewZealand", value: "NZ" },
        { label: "Australia", value: "AU" },
        { label: "Russia", value: "RS" },
        { label: "UAE", value: "UAE" },
        { label: "Cannada", value: "CN" },
        { label: "Norway", value: "NW" },
        { label: "SriLanka", value: "SL" },
      ],
      validation: {
        required: { message: "Select a country" },
        },
    },
  ],
};
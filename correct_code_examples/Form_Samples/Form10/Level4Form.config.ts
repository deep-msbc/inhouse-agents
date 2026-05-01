import type { JSONFormSchema } from "@msbc/config-ui";
import type { Level4FormSchema } from "./level4form.types";

export const Level4Form: JSONFormSchema<Level4FormSchema> = {
    title: "Basic User Pofile",
    layout: { columns: 2 },
    sections: [
        {
            title: "Personal Info",
            layout: { columns: 2 },
            fields: [
                { type: "text", name: "firstName", label: "First Name", validation: { required: { message: "Name is required" } } },
                { type: "text", name: "lastName", label: "Last Name" },
                { type: "text", name: "age", label: "Age", validation: { required: { message: "Age is required" } } },
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
            ],
        },

        {
            title: "Contact Info",
            fields: [
                {
                    type: "text", name: "email", label: "Email",
                    validation: {
                        required: true,
                        pattern: {
                            value: "^[^@]+@[^@]+\\.[^@]+$",
                            message: "Invalid email",
                        },
                    },
                },
                {
                    type: "text", name: "phone", label: "Phone",
                    validation: {
                        required: true,
                        pattern: {
                            value: "^[0-9]{10}$",
                            message: "Phone must be 10 digits"
                        }
                    },
                },
            ],
        },

        {
            title: "Personal ID-Proof",
            name: "personalid",
            repeatable: true,
            minItems: 1,
            maxItems: 5,
            addLabel: "Add ID Proof",
            removeLabel: "Delete",

            fields: [
                {
                    type: "text",
                    name: "title",
                    label: "Id Name",
                    validation: { required: true },
                },
            ],
        }
    ],
};
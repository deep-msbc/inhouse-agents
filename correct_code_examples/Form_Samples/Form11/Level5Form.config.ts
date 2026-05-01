import type { JSONFormSchema } from "@msbc/config-ui";
import type { Level5FormSchema } from "./level5form.types";

export const Level5Form: JSONFormSchema<Level5FormSchema> = {
    title: "Advanced Form",
    layout: { columns: 1 },

    sections: [
        {
            type: "group",
            title: "User Info",
            variant: "card",
            sections: [
                {
                    title: "Basic",
                    fields: [
                        {
                            type: "text",
                            name: "name",
                            label: "Name",
                            validation: { required: true },
                        },
                        {
                            type: "text",
                            name: "age",
                            label: "Age",
                            validation: { required: true }
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
                            name: "phone",
                            label: "Phone",
                            validation: {
                                required: true,
                                pattern: {
                                    value: "^[0-9]{10}$",
                                    message: "Phone must be 10 digits"
                                }
                            },
                        },
                        {
                            type: "select",
                            name: "userType",
                            label: "User Type",
                            options: [
                                { label: "Student", value: "student" },
                                { label: "Employee", value: "employee" },
                            ],
                        },
                        {
                            name: "company",
                            type: "text",
                            label: "Company Name",
                            visibleIf: {
                                field: "userType",
                                operator: "equals",
                                value: "employee",
                            },
                            validation: {
                                requiredIf: {
                                    field: "userType",
                                    operator: "equals",
                                    value: "employee",
                                    message: "Company required",
                                },
                            },
                        },
                    ],
                },
            ],
        },

        {
            title: "Additional Info",
            layout: { columns: 2 },
            fields: [
                {
                    type: "fileUpload",
                    name: "documents",
                    label: "Upload Documents",
                    multiple: true,
                },
            ],
        },
    ],
};
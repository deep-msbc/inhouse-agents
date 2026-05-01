// types.ts
export interface UserFormValues {
  firstName: string;
  lastName: string;
  email: string;
  birthDate?: string; // date picker field
  profilePicture: File[]; // single file upload
  documents: {
    // repeatable section with files
    type: string;
    file: File[];
  }[];
  subscribe: boolean;
  additionalInfo?: string; // conditional field
}

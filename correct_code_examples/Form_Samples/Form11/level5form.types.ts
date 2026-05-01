export interface Level5FormSchema {
  title?: string;
  startDate?: string | Date;

  // User Info
  name: string;
  age: string;
  gender: "M" | "F";

  email: string;
  phone: string;
  userType?: "student" | "employee";
  company?: string;

  // Custom
  rating?: number;

  documents?: any[];   // file upload
}

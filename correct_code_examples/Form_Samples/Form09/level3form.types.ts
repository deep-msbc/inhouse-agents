export interface Level3FormSchema {
  fullName: string;
  email: string;
  age: string;
  Address?: string;

  gender: "M" | "F";

  hobbies: string[]; 

  country: string;
}
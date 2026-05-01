export interface Level4FormSchema {
  firstName: string;
  lastName?: string;
  age: string;
  gender: "M" | "F";

  email: string;
  phone: string;
  personalid: PersonalId[];
}

export interface PersonalId {
  title: string;
  startDate?: Date | string;
}

export interface SectionForm {
  name: string;
  email: string;
  phone: string;

  
}
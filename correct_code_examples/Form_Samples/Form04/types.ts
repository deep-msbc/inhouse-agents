export interface Eventbooking {
  customername: string;
  email: string | number;
  eventdate: Date;
  seatingprefrance: 'indoor' | 'outdoor';
  outdoorarea?: string;
  name: string;
  age: number;
  idproof: File;
  cateringRequired: boolean;
  menuType: string;
  attachments: File;
  addlocation: Map<string, string> | undefined;
  addwishlist: string;
}

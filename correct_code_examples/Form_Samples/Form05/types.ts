export interface Registration {
  firstname: string;
  lastname: string;
  email: string;
  phone: number;
  doa: Date;
  attandance: string;
  workshop: {
    label: string;
    value: string;
  };
  mode: string;
  virtual: string;
  onperson: string;
  idproof: string;
  certificate: string;
  photo: string;
  experience: string;
  participants: Participant[];
}

type Participant = {
  name: string;
  email: string;
  workshopChoice: string;
};

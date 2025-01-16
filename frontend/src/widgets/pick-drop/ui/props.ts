export interface IProps {
  title: string;
  city: string;
  date: string;
  time: string;
  dataChange: (key: keyof Data, val: string) => void;
}

interface Data {
  city: string;
  date: string;
  time: string;
}

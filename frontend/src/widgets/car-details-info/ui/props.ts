import { Car } from "shared/common";

export interface IProps {
  id: string;
  carDetails: Car | null;
  updateLike: (id: string) => void;
}

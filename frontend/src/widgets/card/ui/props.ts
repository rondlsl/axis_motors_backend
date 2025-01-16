import { Car } from "shared/common";

export interface IProps {
  carData: Car;
  onLike: (id: string) => void;
}

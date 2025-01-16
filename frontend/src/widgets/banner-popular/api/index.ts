import axios from "axios";
import { Car } from "shared/common";

export const getCars = async (): Promise<Car[]> => {
  const res = await axios.get(
    `https://665c3c1b3e4ac90a04d9021e.mockapi.io/cars`,
  );
  return res.data;
};

import { Car } from "shared/common";
import axios from "axios";

export const getCars = async (): Promise<Car[]> => {
  const res = await axios.get(
    `https://665c3c1b3e4ac90a04d9021e.mockapi.io/cars`,
  );
  return res.data;
};

export const getCarDetails = async (id: string): Promise<Car> => {
  const res = await axios.get(
    `https://665c3c1b3e4ac90a04d9021e.mockapi.io/cars/${id}`,
  );
  return res.data;
};

export const putLike = async (id: string, liked: boolean): Promise<Car> => {
  const res = await axios.put(
    `https://665c3c1b3e4ac90a04d9021e.mockapi.io/cars/${id}`,
    {
      liked,
    },
  );
  return res.data;
};

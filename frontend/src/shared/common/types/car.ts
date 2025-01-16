export interface Car {
  id: string;
  name: string;
  mode: string;
  transmission: string;
  fuel: number;
  seats: number;
  actualPrice: number;
  discountPrice?: number;
  liked: boolean;
  img: string;
  popular: boolean;
  description: string;
}

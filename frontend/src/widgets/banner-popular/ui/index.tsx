"use client";

import styles from "./styles.module.scss";
import { IProps } from "./props";
import { getCars } from "../api";
import { useEffect, useState } from "react";
import { Car, skeletonArr } from "shared/common";
import { BannerTitle, Button, PageTitle } from "shared/ui";
import { CardSkeleton } from "widgets/card-skeleton";
import { Card } from "widgets/card";
import { pop } from "@jridgewell/set-array";
import { putLike } from "_pages/rent/api";
import { useRouter } from "next/navigation";

export const BannerPopular = (props: IProps) => {
  const [popularCars, setPopularCars] = useState<Car[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  const fetchCars = async () => {
    setIsLoading(true);
    const res = await getCars();
    setPopularCars(res);
    setIsLoading(false);
  };

  const updateLike = async (id: string) => {
    const updatedCars = popularCars.map((c) => {
      if (c.id === id) {
        const updatedCar = { ...c, liked: !c.liked };
        putLike(id, updatedCar.liked);
        return updatedCar;
      }
      return c;
    });

    setPopularCars(updatedCars);
  };

  useEffect(() => {
    fetchCars();
  }, []);

  return (
    <section className={styles.content}>
      <div className={styles.top}>
        <BannerTitle title={"Popular Rental Cars"} />
        <PageTitle title={"Most popular cars rental deals"} subTitle={""} />
      </div>
      <div className={styles.cars}>
        {isLoading
          ? skeletonArr.map((_, index) => <CardSkeleton key={index} />)
          : popularCars.map(
              (c) =>
                c.popular && (
                  <Card key={c.id} carData={c} onLike={updateLike} />
                ),
            )}
      </div>
      <Button
        size={"md"}
        mode={"secondary"}
        onClick={() => router.push("/rent")}
      >
        Show all vehicles
      </Button>
    </section>
  );
};

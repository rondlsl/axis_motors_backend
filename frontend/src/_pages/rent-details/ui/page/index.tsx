"use client";

import styles from "./styles.module.scss";
import { useParams } from "next/navigation";
import { CarDetailsInfo } from "widgets/car-details-info";
import classNames from "classnames";
import { CarDetailsImges } from "widgets/car-details-imges";
import { SectionHeader } from "shared/ui";
import { useEffect, useState } from "react";
import { Car, skeletonArr } from "shared/common";
import { getCarDetails, getCars, putLike } from "_pages/rent-details/api";
import { CardSkeleton } from "widgets/card-skeleton";
import { Card } from "widgets/card";

export const RentDetails = () => {
  const { carId } = useParams();
  const [recommendedCars, setRecommendedCars] = useState<Car[]>([]);
  const [cars, setCars] = useState<Car[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [carDetails, setCarDetails] = useState<Car | null>(null);

  const fetchCars = async () => {
    setIsLoading(true);
    const res = await getCars();
    const recommended = res.filter((c) => c.popular);
    setRecommendedCars(recommended);
    setCars(res);
    setIsLoading(false);
  };

  const fetchCarDetails = async () => {
    const res = await getCarDetails(carId as string);
    setCarDetails(res);
  };

  const updateLike = async (id: string) => {
    const updatedCars = cars.map((c) => {
      if (c.id === id) {
        const updatedCar = { ...c, liked: !c.liked };
        putLike(id, updatedCar.liked); // Await the API call
        return updatedCar;
      }
      return c;
    });

    setCarDetails((prevDetails) =>
      prevDetails?.id == carId
        ? { ...prevDetails, liked: !prevDetails.liked }
        : prevDetails,
    );
    setRecommendedCars((prevRecommended) =>
      prevRecommended.map((c) => (c.id === id ? { ...c, liked: !c.liked } : c)),
    );
    setCars(updatedCars);
  };

  useEffect(() => {
    fetchCarDetails();
    fetchCars();
  }, []);

  return (
    <main className={classNames("wrapper", styles.container)}>
      <div className={styles.content}>
        <div className={styles.top}>
          <CarDetailsImges />
          <CarDetailsInfo
            id={carId as string}
            carDetails={carDetails}
            updateLike={updateLike}
          />
        </div>
        <SectionHeader title={"Recommended Cars"} />
        <div className={styles.bottom}>
          <div className={styles.popularCars}>
            {isLoading ? (
              skeletonArr.map((_, index) => <CardSkeleton key={index} />)
            ) : recommendedCars.length > 0 ? (
              recommendedCars.map(
                (c) =>
                  c.popular && (
                    <Card key={c.id} carData={c} onLike={updateLike} />
                  ),
              )
            ) : (
              <div>No popular cars available.</div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
};

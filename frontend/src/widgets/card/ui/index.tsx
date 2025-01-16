"use client";

import styles from "./styles.module.scss";
import { IProps } from "./props";
import { Like } from "features/like";
import { Button } from "shared/ui";
import Image from "next/image";
import { useRouter } from "next/navigation";
export const Card = ({ carData, onLike }: IProps) => {
  const router = useRouter();

  return (
    <div className={styles.content}>
      <div className={styles.top}>
        <div>
          <p className={styles.name}>{carData.name}</p>
          <p className={styles.mode}>{carData.mode}</p>
        </div>
        <Like liked={carData.liked} carId={carData.id} onLike={onLike} />
      </div>
      <Image
        width={274}
        height={0}
        src={carData.img}
        className={styles.img}
        alt="Car img"
      />
      <div className={styles.mid}>
        <div className={styles.midContent}>
          <div className={styles.info}>
            <Image
              width={24}
              height={24}
              src="/img/utils/gas-station.svg"
              alt="Gas Station"
            />
            <p>{carData.fuel}L</p>
          </div>
          <div className={styles.info}>
            <Image
              width={24}
              height={24}
              src="/img/utils/wheel.svg"
              alt="Wheel"
            />
            <p>{carData.transmission}</p>
          </div>
          <div className={styles.info}>
            <Image
              width={24}
              height={24}
              src="/img/utils/users.svg"
              alt="Users"
            />
            <p>{carData.seats} People</p>
          </div>
        </div>
        <div className={styles.bottom}>
          <div className={styles.price}>
            {carData.discountPrice ? (
              <>
                <p className={styles.discount}>
                  ${carData.discountPrice}/ <span>day</span>
                </p>
                <p className={styles.actual}>${carData.actualPrice}</p>
              </>
            ) : (
              <p className={styles.actualSecond}>
                ${carData.actualPrice}/ <span>day</span>
              </p>
            )}
          </div>
          <Button
            uppercase={false}
            onClick={() => router.push(`/rent/${carData.id}`)}
          >
            Rent Now
          </Button>
        </div>
      </div>
    </div>
  );
};

import styles from "./styles.module.scss";
import { IProps } from "./props";
import Skeleton from "react-loading-skeleton";
import { Like } from "features/like";
import { Button } from "shared/ui";

export const CarDetailsInfo = ({ id, carDetails, updateLike }: IProps) => {
  return (
    <section className={styles.content}>
      <div className={styles.top}>
        <div className={styles.head}>
          <p className={styles.name}>
            {carDetails?.name ? (
              carDetails.name
            ) : (
              <Skeleton
                baseColor={"var(--clr-secondary-skeleton-base)"}
                highlightColor={"var(--clr-secondary-skeleton-highlight)"}
                width={120}
              />
            )}
          </p>
          <Like liked={carDetails?.liked} carId={id} onLike={updateLike} />
        </div>
        <p className={styles.description}>
          {carDetails?.description ? (
            carDetails.description
          ) : (
            <Skeleton
              baseColor={"var(--clr-secondary-skeleton-base)"}
              highlightColor={"var(--clr-secondary-skeleton-highlight)"}
              count={2}
            />
          )}
        </p>
      </div>
      <div className={styles.mid}>
        <div className={styles.info}>
          <div className={styles.infoItem}>
            <p className={styles.infoTitle}>Type Car</p>
            <p className={styles.infoData}>
              {carDetails?.mode ? (
                carDetails.mode
              ) : (
                <Skeleton
                  baseColor={"var(--clr-secondary-skeleton-base)"}
                  highlightColor={"var(--clr-secondary-skeleton-highlight)"}
                  width={72}
                />
              )}
            </p>
          </div>
          <div className={styles.infoItem}>
            <p className={styles.infoTitle}>Steering</p>
            <p className={styles.infoData}>
              {carDetails?.transmission ? (
                carDetails.transmission
              ) : (
                <Skeleton
                  baseColor={"var(--clr-secondary-skeleton-base)"}
                  highlightColor={"var(--clr-secondary-skeleton-highlight)"}
                  width={72}
                />
              )}
            </p>
          </div>
        </div>
        <div className={styles.info}>
          <div className={styles.infoItem}>
            <p className={styles.infoTitle}>Capacity</p>
            <p className={styles.infoData}>
              {carDetails?.seats ? (
                carDetails.seats + " Person"
              ) : (
                <Skeleton
                  baseColor={"var(--clr-secondary-skeleton-base)"}
                  highlightColor={"var(--clr-secondary-skeleton-highlight)"}
                  width={72}
                />
              )}
            </p>
          </div>
          <div className={styles.infoItem}>
            <p className={styles.infoTitle}>Gasoline</p>
            <p className={styles.infoData}>
              {carDetails?.fuel ? (
                carDetails.fuel + "L"
              ) : (
                <Skeleton
                  baseColor={"var(--clr-secondary-skeleton-base)"}
                  highlightColor={"var(--clr-secondary-skeleton-highlight)"}
                  width={72}
                />
              )}
            </p>
          </div>
        </div>
      </div>
      <div className={styles.bottom}>
        <div className={styles.price}>
          {carDetails?.mode ? (
            carDetails.discountPrice ? (
              <>
                <p className={styles.discount}>
                  ${carDetails.discountPrice}/ <span>day</span>
                </p>
                <p className={styles.actual}>${carDetails.actualPrice}</p>
              </>
            ) : (
              <p className={styles.actualSecond}>
                ${carDetails.actualPrice}/ <span>day</span>
              </p>
            )
          ) : (
            <Skeleton
              baseColor={"var(--clr-secondary-skeleton-base)"}
              highlightColor={"var(--clr-secondary-skeleton-highlight)"}
              height={28}
              width={120}
            />
          )}
        </div>
        <Button size={"lg"} uppercase={false}>
          Rent Now
        </Button>
      </div>
    </section>
  );
};

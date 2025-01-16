"use client";

import styles from "./styles.module.scss";
import { IProps } from "./props";
import Image from "next/image";
import { Button } from "shared/ui";
import { useRouter } from "next/navigation";

export const BannerMain = (props: IProps) => {
  const router = useRouter();

  return (
    <section className={styles.content}>
      <div className={styles.left}>
        <p className={styles.title}>Ваше авто может <br/>
            <span className={styles.span}> работать</span> на вас
        </p>
        <p className={styles.subtitle}>
        Превратите авто в источник пассивного дохода и начните зарабатывать с нами!
        </p>
        <div className={styles.links}>
          <Button onClick={() => router.push("/rentout")} size={"md"} className={"font-bold"}>
            Сдать машину
          </Button>
        </div>
      </div>
      <Image
        className={styles.car}
        src={"/img/common/Car-main.png"}
        alt={"Car"}
        width={850}
        height={500}
      />
      <Image
        className={styles.bg}
        src={"/img/common/bg-main.svg"}
        alt={"Bg"}
        width={574}
        height={800}
      />
    </section>
  );
};

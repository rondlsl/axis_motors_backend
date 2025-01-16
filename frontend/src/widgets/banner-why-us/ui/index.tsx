import styles from "./styles.module.scss";
import { IProps } from "./props";
import Image from "next/image";
import { BannerTitle, PageTitle } from "shared/ui";
import { Wallet, ShieldCheck, Clock, PhoneCall } from 'lucide-react'; // импорт иконок
import classNames from "classnames";

export const BannerWhyUs = (props: IProps) => {
  return (
    <section className={styles.content}>
      <Image
        src={"/img/common/bg-why-us.svg"}
        alt={"Bg why us"}
        width={777}
        height={702}
        className={styles.bg}
      />
      <Image
        src={"/img/common/Car-why-us.png"}
        alt={"Audi"}
        width={813}
        height={359}
        className={styles.car}
      />
      <div className={styles.placeholder}></div>
      <div className={styles.right}>
        <BannerTitle title={"Почему выбирают нас"} />
        <PageTitle
          title={"Мы заботимся о вашем авто и вашей безопасности"}
          subTitle={""}
        />
        <div className={styles.pros}>
          <div className={styles.prosItem}>
            <div className={styles.icon}>
              <Wallet size={36} color="#1572d3" />
            </div>
            <div className={classNames(styles.prosText, "space-y-2")}>
              <p className={styles.title}>Забудьте об обслуживании</p>
              <p className={styles.subTitle}>
                Мы покрываем расходы на мойку, топливо и техобслуживание.
              </p>
            </div>
          </div>
          <div className={styles.prosItem}>
            <div className={styles.icon}>
              <ShieldCheck size={36} color="#1572d3" />
            </div>
            <div className={classNames(styles.prosText, "space-y-2")}>
              <p className={styles.title}>Страховка на каждый автомобиль</p>
              <p className={styles.subTitle}>
                Ваше авто застраховано — мы оформляем ОГПО за наш счет.
              </p>
            </div>
          </div>
          <div className={styles.prosItem}>
            <div className={styles.icon}>
              <Clock size={36} color="#1572d3" />
            </div>
            <div className={classNames(styles.prosText, "space-y-2")}>
              <p className={styles.title}>Доступно для вас вне аренды</p>
              <p className={styles.subTitle}>
                Когда ваш автомобиль никем не занят, вы можете использовать его как обычно для своих личных дел.
              </p>
            </div>
          </div>
          <div className={styles.prosItem}>
            <div className={styles.icon}>
              <PhoneCall size={36} color="#1572d3" />
            </div>
            <div className={classNames(styles.prosText, "space-y-2")}>
              <p className={styles.title}>Поддержка 24/7</p>
              <p className={styles.subTitle}>
                Вопросы? Наша команда всегда готова помочь.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

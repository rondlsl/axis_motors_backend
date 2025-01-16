import styles from "./styles.module.scss";
import { IProps } from "./props";
import { BannerTitle, PageTitle } from "shared/ui";
import { CardReview } from "widgets/card-review";
import Image from "next/image";
import classNames from "classnames";

export const BannerReviews = (props: IProps) => {
  return (
    <section className={styles.content}>
      <Image
        src={"/img/utils/quote-bottom.svg"}
        alt={"Quote Icon"}
        width={292}
        height={310}
        className={classNames(styles.quoteIcon, styles.bottom)}
      />
      <Image
        src={"/img/utils/quote-top.svg"}
        alt={"Quote Icon"}
        width={292}
        height={310}
        className={classNames(styles.quoteIcon, styles.top)}
      />
      <div className={styles.top}>
        <BannerTitle title={"Отзывы"} />
        <PageTitle title={"Что говорят о нас клиенты"} subTitle={""} />
      </div>
      <div className={styles.reviews}>
        <CardReview
          review={
            "“Долго искал удобный сервис аренды, и вот нашел это приложение. Машина была в отличном состоянии, как будто моя собственная. Всё быстро, просто.”"
          }
          fullName={"Никита Быков"}
          city={"Алматы"}
          pfp={"/img/common/IMG_2975.jpg"}
        />
        <CardReview
          review={
            "“Сдал свою машину сюда еще месяц назад. Все максимально удобно! Когда нужно, могу взять ее по делам. Всегда есть бензин, авто чистое и обслуженное, так мне еще и за это деньги платят!”"
          }
          fullName={"Илья Осипов"}
          city={"Астана"}
          pfp={"/img/common/user-2.jpg"}
        />
      </div>
    </section>
  );
};

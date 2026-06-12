package com.acme.orders;

import org.springframework.data.jpa.repository.JpaRepository;

public interface OrderRepository extends JpaRepository<Order, Long> {
    java.util.List<Order> findByCustomerId(Long customerId);
}
